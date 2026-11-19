"""One-command four-task HTTP replay and fail-stop check; no model or dataset download."""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def run_check(episode, output, *, fault=None, video=True):
    output.mkdir(parents=True, exist_ok=False)
    server_args = [sys.executable, "scripts/serve_action_replay.py", str(episode),
                   "--port", "0", "--trace", str(output / "server_requests.jsonl")]
    if fault:
        server_args.extend(["--inject-fault", fault])
    with (output / "server.log").open("w", encoding="utf-8") as server_log:
        server = subprocess.Popen(server_args, stdout=server_log, stderr=subprocess.STDOUT,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 20
            announcement = None
            while time.monotonic() < deadline:
                for line in (output / "server.log").read_text(encoding="utf-8").splitlines():
                    try:
                        value = json.loads(line)
                        if "endpoint" in value:
                            announcement = value
                            break
                    except ValueError:
                        pass
                if announcement:
                    break
                if server.poll() is not None:
                    raise RuntimeError(f"Server exited; inspect {output / 'server.log'}")
                time.sleep(.05)
            if not announcement:
                raise TimeoutError("Replay server did not start in 20 seconds")
            command = [sys.executable, "scripts/remote_policy_rollout.py",
                "--endpoint", announcement["endpoint"], "--source-episode", str(episode),
                "--output", str(output / "rollout")]
            if not video or fault:
                command.append("--no-video")
            if fault == "timeout":
                command.extend(["--timeout", ".5"])
            with (output / "client.log").open("w", encoding="utf-8") as client_log:
                process = subprocess.run(command, stdout=client_log, stderr=subprocess.STDOUT,
                    timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            report_path = output / "rollout/report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            client_events = [json.loads(line) for line in (output / "rollout/requests.jsonl").read_text().splitlines()]
            server_events = [json.loads(line) for line in (output / "server_requests.jsonl").read_text().splitlines()]
            if report["learned_policy"] or report["max_sim_time_advance_during_request_s"] != 0:
                raise RuntimeError("Replay provenance or paused simulation check failed")
            if fault:
                expected_error = "episode_id" if fault == "stale_episode" else "timed out"
                passed = (process.returncode == 1 and report["steps"] == 5
                    and report["accepted_requests"] == 1 and report["rejected_requests"] == 1
                    and expected_error in report["error"]
                    and client_events[-1]["steps_before"] == client_events[-1]["steps_after"] == 5
                    and client_events[-1]["sim_time_before_s"] == client_events[-1]["sim_time_after_s"])
            else:
                expected_shapes = {"observation.state": [9], "observation.images.front": [256, 256, 3],
                                   "observation.images.wrist": [256, 256, 3]}
                passed = (process.returncode == 0 and report["replay_within_tolerance"]
                    and report["rejected_requests"] == 0
                    and len(server_events) == len(client_events) == report["accepted_requests"]
                    and sum(event["actions_executed"] for event in client_events) == report["steps"]
                    and all(event["decoded_shapes"] == expected_shapes for event in server_events)
                    and all(server_event["request_id"] == client_event["request_id"]
                            and server_event["input_sha256"] == client_event["input_sha256"]
                            for server_event, client_event in zip(server_events, client_events)))
            result = dict(check=fault or episode.parent.name, passed=passed,
                client_exit_code=process.returncode, report=report,
                server_requests=len(server_events), distinct_input_hashes=len({e["input_sha256"] for e in server_events}),
                client_trace_sha256=hashlib.sha256((output / "rollout/requests.jsonl").read_bytes()).hexdigest(),
                server_trace_sha256=hashlib.sha256((output / "server_requests.jsonl").read_bytes()).hexdigest())
            if not passed:
                raise RuntimeError(f"Check failed: {result['check']}; inspect {report_path}")
            return result
        finally:
            if server.poll() is None:
                server.terminate()
            server.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", type=Path, required=True,
                        help="Existing recorded condition with open_top/open_bottom/close_top/close_bottom")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    if not Path("src/pi05_cabinet/inference.py").exists():
        parser.error("Run this command from the repository root")
    names = ("open_top", "open_bottom", "close_top", "close_bottom")
    for name in names:
        if not (args.condition / name / "episode.hdf5").is_file():
            parser.error(f"Missing completed recording: {name}")
    args.output.mkdir(parents=True, exist_ok=False)
    source_names = ("src/pi05_cabinet/inference.py", "scripts/serve_action_replay.py",
                    "scripts/remote_policy_rollout.py", "scripts/check_remote_chunks.py", "tests/test_inference.py")
    summary = dict(schema="cabinet_remote_chunks_check_v1", mode="RECORDED_ACTION_CHUNKS",
        learned_policy=False, created_utc=datetime.now(timezone.utc).isoformat(),
        source_code_sha256={name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in source_names},
        scope="Recorded actions over loopback HTTP, not pi0.5 inference or policy evaluation",
        horizon=50, execute_steps=5, checks=[])
    try:
        for name in names:
            result = run_check(args.condition / name / "episode.hdf5", args.output / name,
                               video=not args.no_video)
            summary["checks"].append(result)
            print(json.dumps(dict(check=name, passed=result["passed"], steps=result["report"]["steps"])), flush=True)
        for fault in ("stale_episode", "timeout"):
            result = run_check(args.condition / "open_top/episode.hdf5", args.output / fault,
                               fault=fault, video=False)
            summary["checks"].append(result)
            print(json.dumps(dict(check=fault, passed=result["passed"], steps=result["report"]["steps"])), flush=True)
    finally:
        summary["all_passed"] = len(summary["checks"]) == 6 and all(check["passed"] for check in summary["checks"])
        (args.output / "report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not summary["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
