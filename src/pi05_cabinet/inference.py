"""Versioned, synchronous action-chunk transport; no model dependencies.

The wire observation contains only language, two RGB images and proprioception.
Responses are checked in full before the caller can execute any action.
"""
import base64
import hashlib
import io
import json
import time
import uuid
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import numpy as np
from PIL import Image

from .adapters import SCHEMA_VERSION

PROTOCOL = "cabinet_action_chunk_v1"
REPLAY_MODE = "RECORDED_ACTION_CHUNKS"
MODEL_MODE = "PI05"
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
RGB_KEYS = ("observation.images.front", "observation.images.wrist")
CONTEXT_KEYS = (
    "protocol", "observation_schema", "episode_id", "request_id", "step_index",
    "checkpoint_id", "front_camera", "horizon", "execute_steps", "control_hz",
    "input_sha256",
)


class InferenceError(ValueError):
    """An input, response or transport failure: advance no simulation steps."""


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _number_array(value, shape, name):
    try:
        array = np.asarray(value)
        if array.shape != shape or array.dtype.kind not in "iuf":
            raise ValueError()
        array = array.astype(np.float64)
        if not np.isfinite(array).all():
            raise ValueError()
        return array
    except (ValueError, TypeError, OverflowError) as error:
        raise InferenceError(f"Expected finite numeric {name} with shape {shape}") from error


def _positive_int(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise InferenceError(f"Invalid {name}; expected integer in [1,{maximum}]")


def _text(value, name, maximum=256):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InferenceError(f"Invalid {name}")


def _encode_rgb(image):
    image = np.asarray(image)
    if image.shape != (256, 256, 3) or image.dtype != np.uint8:
        raise InferenceError("Expected top-left uint8 RGB [256,256,3]")
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, format="PNG", compress_level=1)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def _decode_rgb(encoded):
    try:
        if not isinstance(encoded, str) or len(encoded) > 400_000:
            raise ValueError()
        data = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.mode != "RGB" or image.size != (256, 256):
                raise ValueError()
            return np.asarray(image).copy()
    except (ValueError, OSError, TypeError) as error:
        raise InferenceError("Invalid RGB PNG payload") from error


def _input_digest(instruction, observation):
    return hashlib.sha256(json_bytes(dict(instruction=instruction, observation=observation))).hexdigest()


def make_request(observation, instruction, *, episode_id, step_index, checkpoint_id,
                 horizon=50, execute_steps=5):
    if set(observation) != {"observation.state", *RGB_KEYS}:
        raise InferenceError("Policy observation must contain only state and two RGB images")
    state = _number_array(observation["observation.state"], (9,), "state")
    packed = {"observation.state": state.tolist()}
    packed.update({key: _encode_rgb(observation[key]) for key in RGB_KEYS})
    request = dict(protocol=PROTOCOL, observation_schema=SCHEMA_VERSION,
        episode_id=episode_id, request_id=str(uuid.uuid4()), step_index=step_index,
        checkpoint_id=checkpoint_id, front_camera="cabinet_front", horizon=horizon,
        execute_steps=execute_steps, control_hz=20, instruction=instruction,
        observation=packed, input_sha256=_input_digest(instruction, packed))
    validate_request(request, decode_images=False)
    return request


def validate_request(request, *, decode_images=True):
    if not isinstance(request, dict) or set(request) != {*CONTEXT_KEYS, "instruction", "observation"}:
        raise InferenceError("Unexpected request fields")
    if request["protocol"] != PROTOCOL or request["observation_schema"] != SCHEMA_VERSION:
        raise InferenceError("Unsupported protocol or observation schema")
    for key in ("episode_id", "request_id", "checkpoint_id"):
        _text(request[key], key)
    _text(request["instruction"], "instruction", 512)
    if type(request["step_index"]) is not int or not 0 <= request["step_index"] < 600:
        raise InferenceError("Invalid step_index")
    _positive_int(request["horizon"], "horizon", 128)
    _positive_int(request["execute_steps"], "execute_steps", request["horizon"])
    if request["front_camera"] != "cabinet_front" or type(request["control_hz"]) is not int or request["control_hz"] != 20:
        raise InferenceError("Expected cabinet_front at 20 Hz")
    packed = request["observation"]
    if not isinstance(packed, dict) or set(packed) != {"observation.state", *RGB_KEYS}:
        raise InferenceError("Unexpected observation fields")
    state = _number_array(packed["observation.state"], (9,), "state")
    try:
        digest = _input_digest(request["instruction"], packed)
    except (ValueError, TypeError) as error:
        raise InferenceError("Invalid observation encoding") from error
    if request["input_sha256"] != digest:
        raise InferenceError("Instruction/observation digest mismatch")
    decoded = {"observation.state": state}
    if decode_images:
        decoded.update({key: _decode_rgb(packed[key]) for key in RGB_KEYS})
    return decoded


def request_context(request):
    return {key: request[key] for key in CONTEXT_KEYS}


def make_response(request, actions, *, mode):
    if mode not in (REPLAY_MODE, MODEL_MODE):
        raise InferenceError("Unknown policy mode")
    response = dict(request_context(request), policy_mode=mode,
                    learned_policy=mode == MODEL_MODE, actions=np.asarray(actions).tolist())
    validate_response(response, request, expected_mode=mode)
    return response


def validate_response(response, request, *, expected_mode):
    if expected_mode not in (REPLAY_MODE, MODEL_MODE):
        raise InferenceError("Unknown expected policy mode")
    if not isinstance(response, dict) or set(response) != {*CONTEXT_KEYS, "policy_mode", "learned_policy", "actions"}:
        raise InferenceError("Unexpected response fields")
    for key in CONTEXT_KEYS:
        if type(response[key]) is not type(request[key]) or response[key] != request[key]:
            raise InferenceError(f"Response {key} does not match current request")
    if response["policy_mode"] != expected_mode or type(response["learned_policy"]) is not bool or response["learned_policy"] != (expected_mode == MODEL_MODE):
        raise InferenceError("Response policy provenance does not match expected mode")
    actions = _number_array(response["actions"], (request["horizon"], 7), "action chunk")
    if np.any(np.abs(actions) > 1):
        raise InferenceError("Action chunk outside normalized [-1,1]; refusing to clip")
    return actions


@dataclass
class ChunkReply:
    actions: np.ndarray
    context: dict
    latency_s: float
    request_bytes: int
    response_bytes: int


class ActionChunkClient:
    def __init__(self, endpoint, *, checkpoint_id, expected_mode, timeout_s=10.):
        endpoint_parts = urlsplit(endpoint)
        if (endpoint_parts.scheme not in ("http", "https") or not endpoint_parts.hostname
                or endpoint_parts.username or endpoint_parts.password
                or endpoint_parts.query or endpoint_parts.fragment
                or endpoint_parts.path != "/predict"):
            raise InferenceError("Expected an HTTP(S) /predict endpoint without URL credentials")
        if not np.isfinite(timeout_s) or not 0 < timeout_s <= 60:
            raise InferenceError("timeout_s must be in (0,60]")
        _text(checkpoint_id, "checkpoint_id")
        if expected_mode not in (REPLAY_MODE, MODEL_MODE):
            raise InferenceError("Unknown expected policy mode")
        self.endpoint, self.checkpoint_id = endpoint, checkpoint_id
        self.expected_mode, self.timeout_s = expected_mode, timeout_s
        self.opener = build_opener(ProxyHandler({}))
        self.last_request_context = None

    def fetch(self, observation, instruction, *, episode_id, step_index, horizon=50, execute_steps=5):
        request = make_request(observation, instruction, episode_id=episode_id,
            step_index=step_index, checkpoint_id=self.checkpoint_id,
            horizon=horizon, execute_steps=execute_steps)
        self.last_request_context = request_context(request)
        payload = json_bytes(request)
        if len(payload) > MAX_MESSAGE_BYTES:
            raise InferenceError("Request exceeds message size limit")
        started = time.perf_counter()
        try:
            http_request = Request(self.endpoint, data=payload, method="POST",
                                   headers={"Content-Type": "application/json"})
            with self.opener.open(http_request, timeout=self.timeout_s) as stream:
                body = stream.read(MAX_MESSAGE_BYTES + 1)
        except HTTPError as error:
            raise InferenceError(f"Policy endpoint returned HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError, HTTPException) as error:
            raise InferenceError("Policy transport failed or timed out") from error
        elapsed = time.perf_counter() - started
        if elapsed > self.timeout_s:
            raise InferenceError("Policy response arrived after the request deadline")
        if len(body) > MAX_MESSAGE_BYTES:
            raise InferenceError("Response exceeds message size limit")
        try:
            response = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            raise InferenceError("Policy response is not JSON") from error
        actions = validate_response(response, request, expected_mode=self.expected_mode)
        return ChunkReply(actions=actions, context=self.last_request_context.copy(),
            latency_s=elapsed, request_bytes=len(payload), response_bytes=len(body))
