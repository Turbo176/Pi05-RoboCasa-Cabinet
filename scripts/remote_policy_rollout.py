"""Run validated HTTP action chunks in MuJoCo; recorded chunks are labeled replay.

No pi0.5 server is supplied here. PI05 mode requires a separately implemented
model endpoint with matching checkpoint, processors, cameras and action units.
"""
import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

from _windows_runtime import prepare_runtime
_runtime = prepare_runtime()

import h5py
import imageio.v2 as imageio
import numpy as np
from pi05_cabinet.adapters import policy_observation, robot_action
from pi05_cabinet.envs import add_scene_arguments, make_env_from_args, make_lite_env
from pi05_cabinet.inference import ActionChunkClient, MODEL_MODE, REPLAY_MODE
from pi05_cabinet.recording import label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_scene_arguments(parser)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--checkpoint-id")
    parser.add_argument("--expected-mode", choices=(REPLAY_MODE, MODEL_MODE), default=REPLAY_MODE)
    parser.add_argument("--source-episode", type=Path,
        help="Recorded mode only: reconstruct and compare the exact source scene")
    parser.add_argument("--horizon", type=int, default=50)
    parser.add_argument("--execute-steps", type=int, default=5)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--timeout", type=float, default=10.)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_steps <= 600 or not 1 <= args.execute_steps <= args.horizon <= 128:
        parser.error("Expected 1..600 steps and 1 <= execute_steps <= horizon <= 128")
    if (args.expected_mode == REPLAY_MODE) != bool(args.source_episode):
        parser.error("Recorded mode requires --source-episode; PI05 mode uses scene arguments")
    if args.front_camera != "cabinet_front":
        parser.error("Remote policy contract requires cabinet_front")
    source = None
    if args.source_episode:
        with args.source_episode.open("rb") as stream:
            source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        with h5py.File(args.source_episode, "r") as file:
            if args.source_episode.name != "episode.hdf5" or not bool(file.attrs.get("complete", False)):
                raise ValueError("Expected completed episode.hdf5")
            source = dict(metadata=json.loads(file.attrs["metadata_json"]),
                initial=file["initial_sim_state"][:], xml=file["model_xml"][()].decode(),
                actions=file["actions"][:], joints=file["observations/robot0_joint_pos"][:],
                fractions=file["evaluation/drawer_open_fractions"][:], sha256=source_hash)
        if source["metadata"].get("scene_parameters", {}).get("front_camera") != "cabinet_front":
            raise ValueError("Source episode uses a different camera contract")
        args.checkpoint_id = args.checkpoint_id or "recorded:" + source_hash
    if not args.checkpoint_id:
        parser.error("PI05 mode requires an explicit --checkpoint-id")
    client = ActionChunkClient(args.endpoint, checkpoint_id=args.checkpoint_id,
        expected_mode=args.expected_mode, timeout_s=args.timeout)
    args.output.mkdir(parents=True, exist_ok=False)
    if source:
        metadata = source["metadata"]
        env = make_lite_env(metadata["task_variant"], metadata["seed"], **metadata["scene_parameters"])
    else:
        env = make_env_from_args(args)
    report = dict(schema="cabinet_remote_rollout_v1", mode=args.expected_mode,
        learned_policy=args.expected_mode == MODEL_MODE, checkpoint_id=args.checkpoint_id,
        episode_id=str(uuid.uuid4()), benchmark="custom Lite; not full RoboCasa benchmark",
        horizon=args.horizon, execute_steps=args.execute_steps, control_hz=20,
        max_control_steps=args.max_steps, steps=0, accepted_requests=0, rejected_requests=0,
        success_final=False, success_stable_last_10=False,
        stop_reason="not_started", simulation_advances_while_waiting=False,
        max_sim_time_advance_during_request_s=0.)
    if source:
        report.update(source_episode_sha256=source["sha256"],
            source_policy_mode=source["metadata"]["policy_mode"],
            recorded_actions=len(source["actions"]), max_joint_replay_error_rad=0.,
            max_drawer_replay_error=0., max_robot_action_replay_error=0.)
    writer, request_log = None, None
    latencies, successes = [], []
    started = time.perf_counter()
    error = None
    try:
        obs = env.reset()
        if source:
            if env.sim.model.get_xml() != source["xml"]:
                raise ValueError("Source XML differs from current environment")
            reset_error = float(np.max(np.abs(env.sim.get_state().flatten() - source["initial"])))
            report["initial_state_max_error"] = reset_error
            if reset_error > 1e-8:
                raise ValueError("Source initial state differs from seeded reset")
            env.sim.set_state_from_flattened(source["initial"])
            env.sim.forward()
        metadata = env.get_ep_meta()
        seed = source["metadata"]["seed"] if source else args.seed
        report.update(task=metadata.get("task_variant", type(env).__name__), seed=seed, language=metadata["lang"],
                      scene_parameters=metadata.get("scene_parameters", {}))
        budget = min(args.max_steps, len(source["actions"])) if source else args.max_steps
        request_log = (args.output / "requests.jsonl").open("x", encoding="utf-8")
        if not args.no_video:
            writer = imageio.get_writer(args.output / "rollout.mp4", fps=20, codec="libx264")
        while report["steps"] < budget:
            step = report["steps"]
            sim_time_before = float(env.sim.data.time)
            try:
                reply = client.fetch(policy_observation(obs), metadata["lang"],
                    episode_id=report["episode_id"], step_index=step,
                    horizon=args.horizon, execute_steps=args.execute_steps)
            except Exception as failure:
                report["rejected_requests"] += 1
                request_log.write(json.dumps(dict(context=client.last_request_context,
                    accepted=False, steps_before=step, steps_after=report["steps"],
                    sim_time_before_s=sim_time_before, sim_time_after_s=float(env.sim.data.time),
                    error_type=type(failure).__name__, error=str(failure))) + "\n")
                request_log.flush()
                raise
            finally:
                advance = float(env.sim.data.time) - sim_time_before
                report["max_sim_time_advance_during_request_s"] = max(
                    report["max_sim_time_advance_during_request_s"], abs(advance))
                report["simulation_advances_while_waiting"] |= advance != 0.
            count = min(args.execute_steps, budget - step)
            event = dict(reply.context, accepted=True, latency_s=reply.latency_s,
                request_bytes=reply.request_bytes, response_bytes=reply.response_bytes,
                sim_time_before_s=sim_time_before, sim_time_after_s=float(env.sim.data.time),
                actions_returned=len(reply.actions), actions_executed=0)
            report["accepted_requests"] += 1
            latencies.append(reply.latency_s)
            for action in reply.actions[:count]:
                full_action = robot_action(action)
                obs, reward, done, info = env.step(full_action)
                report["steps"] += 1
                event["actions_executed"] += 1
                successes.append(bool(env._check_success()))
                metrics = env.task_metrics() if hasattr(env, "task_metrics") else None
                if source:
                    i = report["steps"]
                    report["max_joint_replay_error_rad"] = max(report["max_joint_replay_error_rad"],
                        float(np.max(np.abs(obs["robot0_joint_pos"] - source["joints"][i]))))
                    report["max_drawer_replay_error"] = max(report["max_drawer_replay_error"],
                        float(np.max(np.abs(np.array(list(metrics["drawer_fractions"].values())) - source["fractions"][i]))))
                    report["max_robot_action_replay_error"] = max(report["max_robot_action_replay_error"],
                        float(np.max(np.abs(full_action - source["actions"][i-1]))))
                if writer:
                    rgb = env.sim.render(width=640, height=480, camera_name="cabinet_overview")[::-1].copy()
                    opening = float(env.drawer.get_door_state(env=env)["door"])
                    writer.append_data(label(rgb, report["task"], seed,
                        f"chunk@{step}", opening, successes[-1], mode=args.expected_mode,
                        instruction=metadata["lang"], task_metrics=metrics))
                if done:
                    report["stop_reason"] = "environment_done"
                    break
                if not source and len(successes) >= 10 and all(successes[-10:]):
                    report["stop_reason"] = "stable_success"
                    break
            request_log.write(json.dumps(event) + "\n")
            request_log.flush()
            if report["stop_reason"] in ("environment_done", "stable_success"):
                break
        if report["stop_reason"] == "not_started":
            report["stop_reason"] = "recording_end" if source and report["steps"] == len(source["actions"]) else "step_budget"
        report["success_final"] = bool(successes and successes[-1])
        report["success_stable_last_10"] = len(successes) >= 10 and all(successes[-10:])
        if source:
            report["all_recorded_actions_executed"] = report["steps"] == len(source["actions"])
            report["replay_within_tolerance"] = (report["all_recorded_actions_executed"]
                and report["max_joint_replay_error_rad"] < .01 and report["max_drawer_replay_error"] < .01
                and report["max_robot_action_replay_error"] < 1e-6)
            if not report["replay_within_tolerance"]:
                raise RuntimeError("Recorded action-chunk replay is incomplete or exceeded tolerance")
    except Exception as failure:
        error = failure
        report.update(stop_reason="error", error_type=type(failure).__name__, error=str(failure))
    finally:
        if request_log:
            request_log.close()
        if writer:
            writer.close()
        if successes:
            report["success_final"] = successes[-1]
            report["success_stable_last_10"] = len(successes) >= 10 and all(successes[-10:])
        if hasattr(env, "task_metrics"):
            report["evaluation"] = env.task_metrics()
        env.close()
        report.update(wall_seconds=time.perf_counter()-started,
            latency_seconds=dict(count=len(latencies), mean=float(np.mean(latencies)) if latencies else None,
                p95=float(np.percentile(latencies, 95)) if latencies else None,
                maximum=max(latencies) if latencies else None))
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
