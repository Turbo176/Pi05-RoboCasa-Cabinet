"""Loopback-only recorded-action endpoint for testing transport, not a VLA model."""
import argparse
import hashlib
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

import h5py
import numpy as np

from pi05_cabinet.adapters import policy_action
from pi05_cabinet.inference import (MAX_MESSAGE_BYTES, REPLAY_MODE, InferenceError,
    json_bytes, make_response, request_context, validate_request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--trace", type=Path, help="Optional new JSONL request log")
    parser.add_argument("--inject-fault", choices=("stale_episode", "timeout"),
                        help="Diagnostic only: invalidate responses from --fault-at-step")
    parser.add_argument("--fault-at-step", type=int, default=5)
    args = parser.parse_args()
    with args.episode.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    with h5py.File(args.episode, "r") as file:
        if args.episode.name != "episode.hdf5" or not bool(file.attrs.get("complete", False)):
            raise ValueError("Expected completed episode.hdf5")
        metadata = json.loads(file.attrs["metadata_json"])
        actions = np.array([policy_action(action) for action in file["actions"][:]])
    if not len(actions) or len(actions) > 600:
        raise ValueError("Expected 1..600 recorded actions")
    if metadata.get("scene_parameters", {}).get("front_camera") != "cabinet_front":
        raise ValueError("This endpoint tests the cabinet_front contract only")
    checkpoint_id = "recorded:" + source_hash
    lock = Lock()
    trace = None
    if args.trace:
        args.trace.parent.mkdir(parents=True, exist_ok=True)
        trace = args.trace.open("x", encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            body = json_bytes(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, dict(ready=True, policy_mode=REPLAY_MODE,
                    learned_policy=False, checkpoint_id=checkpoint_id, steps=len(actions)))
            else:
                self.reply(404, dict(error="Unknown path"))

        def do_POST(self):
            self.connection.settimeout(10.)
            try:
                if self.path != "/predict":
                    self.reply(404, dict(error="Unknown path"))
                    return
                if self.headers.get("Content-Type") != "application/json":
                    raise InferenceError("Expected application/json")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_MESSAGE_BYTES:
                    raise InferenceError("Invalid message length")
                request = json.loads(self.rfile.read(size))
                observation = validate_request(request)
                if request["checkpoint_id"] != checkpoint_id:
                    raise InferenceError("Wrong recorded checkpoint")
                if request["instruction"] != metadata["lang"]:
                    raise InferenceError("Instruction differs from the recorded source")
                if request["step_index"] >= len(actions):
                    raise InferenceError("Request is past recording end")
                indices = np.minimum(np.arange(request["horizon"]) + request["step_index"], len(actions)-1)
                response = make_response(request, actions[indices], mode=REPLAY_MODE)
                fault = args.inject_fault if request["step_index"] >= args.fault_at_step else None
                if trace:
                    with lock:
                        trace.write(json.dumps(dict(request_context(request),
                            decoded_shapes={key: list(value.shape) for key, value in observation.items()},
                            request_bytes=size, mode=REPLAY_MODE, learned_policy=False,
                            injected_fault=fault)) + "\n")
                        trace.flush()
                if fault == "stale_episode":
                    response["episode_id"] = "previous-episode"
                elif fault == "timeout":
                    time.sleep(2.)
                self.reply(200, response)
            except (ValueError, TypeError, KeyError, OSError) as error:
                self.reply(400, dict(error=str(error)))

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps(dict(endpoint=f"http://127.0.0.1:{server.server_port}/predict",
        checkpoint_id=checkpoint_id, mode=REPLAY_MODE, learned_policy=False)), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if trace:
            trace.close()


if __name__ == "__main__":
    main()
