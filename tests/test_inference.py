"""Transport faults that must be rejected before control receives a chunk."""
import copy
import json
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from pi05_cabinet.inference import (ActionChunkClient, InferenceError, MAX_MESSAGE_BYTES, MODEL_MODE,
    REPLAY_MODE, json_bytes, make_request, make_response, validate_request, validate_response)


def observation():
    image = np.zeros((256, 256, 3), dtype=np.uint8)
    image[0, :, 0] = 255
    image[-1, :, 2] = 127
    return {"observation.state": np.arange(9, dtype=np.float32) / 10,
        "observation.images.front": image, "observation.images.wrist": image[:, ::-1].copy()}


def request():
    return make_request(observation(), "Open the top drawer.", episode_id="episode-a",
                        step_index=0, checkpoint_id="test-checkpoint")


@contextmanager
def endpoint(modifier=None, delay=0., raw_response=None, status=200):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            validate_request(value)
            response = make_response(value, np.zeros((value["horizon"], 7)), mode=REPLAY_MODE)
            if modifier:
                modifier(response)
            payload = raw_response if raw_response is not None else json_bytes(response)
            time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/predict"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.)


class InferenceTests(unittest.TestCase):
    def test_png_roundtrip_preserves_both_views_and_row_direction(self):
        source = observation()
        decoded = validate_request(request())
        for key in source:
            np.testing.assert_array_equal(decoded[key], source[key])

    def test_privileged_fields_cannot_be_added(self):
        value = observation()
        value["drawer_open_fraction"] = .5
        with self.assertRaises(InferenceError):
            make_request(value, "Open.", episode_id="a", step_index=0, checkpoint_id="b")
        value = request()
        value["target_handle_position"] = [1, 2, 3]
        with self.assertRaises(InferenceError):
            validate_request(value)

    def test_instruction_or_image_tampering_changes_digest(self):
        for field in ("instruction", "observation"):
            value = request()
            if field == "instruction":
                value[field] = "Open the bottom drawer."
            else:
                value[field]["observation.images.front"] = value[field]["observation.images.front"][:-4]
            with self.subTest(field=field), self.assertRaises(InferenceError):
                validate_request(value)

    def test_invalid_state_is_rejected(self):
        for invalid in ([0.] * 8, [float("nan")] * 9, ["0"] * 9):
            value = observation()
            value["observation.state"] = invalid
            with self.subTest(invalid=repr(invalid)), self.assertRaises(InferenceError):
                make_request(value, "Open.", episode_id="a", step_index=0, checkpoint_id="b")

    def test_request_limits_reject_invalid_configuration(self):
        for overrides in (dict(step_index=-1), dict(step_index=True), dict(step_index=600),
                          dict(horizon=0), dict(horizon=129), dict(execute_steps=51)):
            args = dict(episode_id="a", step_index=0, checkpoint_id="b")
            args.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(InferenceError):
                make_request(observation(), "Open.", **args)

    def test_old_episode_request_step_or_checkpoint_is_rejected(self):
        value = request()
        good = make_response(value, np.zeros((50, 7)), mode=REPLAY_MODE)
        for field in ("episode_id", "request_id", "checkpoint_id", "input_sha256",
                      "step_index", "horizon", "execute_steps", "control_hz", "front_camera",
                      "protocol", "observation_schema"):
            response = copy.deepcopy(good)
            response[field] = response[field] + 1 if type(response[field]) is int else response[field] + "-old"
            with self.subTest(field=field), self.assertRaises(InferenceError):
                validate_response(response, value, expected_mode=REPLAY_MODE)

    def test_entire_action_chunk_is_validated_including_unused_tail(self):
        value = request()
        for invalid in (np.zeros((49, 7)), np.zeros((50, 8)), np.full((50, 7), np.nan)):
            response = make_response(value, np.zeros((50, 7)), mode=REPLAY_MODE)
            response["actions"] = invalid.tolist()
            with self.subTest(shape=invalid.shape), self.assertRaises(InferenceError):
                validate_response(response, value, expected_mode=REPLAY_MODE)
        response = make_response(value, np.zeros((50, 7)), mode=REPLAY_MODE)
        response["actions"][-1][-1] = 1.01
        with self.assertRaises(InferenceError):
            validate_response(response, value, expected_mode=REPLAY_MODE)

    def test_replay_cannot_be_accepted_as_model_output(self):
        value = request()
        response = make_response(value, np.zeros((50, 7)), mode=REPLAY_MODE)
        with self.assertRaises(InferenceError):
            validate_response(response, value, expected_mode=MODEL_MODE)
        response["learned_policy"] = 0
        with self.assertRaises(InferenceError):
            validate_response(response, value, expected_mode=REPLAY_MODE)

    def test_http_roundtrip(self):
        with endpoint() as url:
            client = ActionChunkClient(url, checkpoint_id="test", expected_mode=REPLAY_MODE)
            result = client.fetch(observation(), "Open.", episode_id="a", step_index=0)
            self.assertEqual(result.actions.shape, (50, 7))
            self.assertEqual(result.context["episode_id"], "a")
            self.assertGreater(result.request_bytes, 0)

    def test_http_stale_reply_is_rejected(self):
        with endpoint(lambda response: response.update(episode_id="previous-episode")) as url:
            client = ActionChunkClient(url, checkpoint_id="test", expected_mode=REPLAY_MODE)
            with self.assertRaises(InferenceError):
                client.fetch(observation(), "Open.", episode_id="a", step_index=0)

    def test_http_timeout_has_no_returned_chunk(self):
        with endpoint(delay=.15) as url:
            client = ActionChunkClient(url, checkpoint_id="test", expected_mode=REPLAY_MODE, timeout_s=.03)
            with self.assertRaises(InferenceError):
                client.fetch(observation(), "Open.", episode_id="a", step_index=0)

    def test_http_invalid_json_or_server_error_is_rejected(self):
        for body, status in ((b"not-json", 200), (b"{}", 503), (b" " * (MAX_MESSAGE_BYTES + 1), 200)):
            with self.subTest(status=status), endpoint(raw_response=body, status=status) as url:
                client = ActionChunkClient(url, checkpoint_id="test", expected_mode=REPLAY_MODE)
                with self.assertRaises(InferenceError):
                    client.fetch(observation(), "Open.", episode_id="a", step_index=0)


if __name__ == "__main__":
    unittest.main()
