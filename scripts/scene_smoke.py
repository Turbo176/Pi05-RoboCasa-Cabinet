"""Reset and step a RoboCasa drawer scene; this does not solve the task."""
import argparse
import json
import time
from pathlib import Path

from _windows_runtime import prepare_runtime
_runtime = prepare_runtime()

import imageio.v2 as imageio
import numpy as np
from pi05_cabinet.envs import add_scene_arguments, make_env_from_args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_scene_arguments(parser)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--output", type=Path, default=Path("outputs/scene_smoke"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    env = make_env_from_args(args)
    try:
        start = time.perf_counter()
        obs = env.reset()
        reset_seconds = time.perf_counter() - start
        keys = [k for k in obs if k.endswith("_image")]
        assert len(keys) == 2, keys
        state_keys = [k for k in obs if "joint_pos" in k or "eef_pos" in k or "gripper_qpos" in k]
        assert state_keys, list(obs)
        initial = env.drawer.get_door_state(env=env)
        action = np.zeros(env.action_dim)
        action[6] = -1  # keep gripper open
        started = time.perf_counter()
        with imageio.get_writer(args.output / "scene_smoke.mp4", fps=20, codec="libx264") as writer:
            for i in range(args.steps):
                obs, reward, done, info = env.step(action)
                images = [obs[k][::-1].copy() for k in keys]  # OpenGL -> top-left RGB
                assert all(im.shape == (256, 256, 3) and im.std() > 5 for im in images)
                frame = np.concatenate(images, axis=1)
                writer.append_data(frame)
                if i == 0:
                    imageio.imwrite(args.output / "scene_smoke.png", frame)
        elapsed = time.perf_counter() - started
        report = dict(
            task=args.task, benchmark="custom Lite; no sampled objects; not full RoboCasa",
            seed=args.seed, mode="SMOKE_ZERO_ACTIONS", learned_policy=False,
            reset_seconds=reset_seconds, steps=args.steps,
            wall_seconds=elapsed, steps_per_second=args.steps/elapsed,
            action_dim=env.action_dim, camera_keys=keys,
            observation_shapes={k:list(np.asarray(v).shape) for k,v in obs.items()},
            language=env.get_ep_meta()["lang"],
            initial_drawer_state=initial, final_drawer_state=env.drawer.get_door_state(env=env),
            success=bool(env._check_success()),
        )
        if hasattr(env, "task_metrics"):
            report.update(env.task_metrics())
            report["scene_parameters"] = env.get_ep_meta()["scene_parameters"]
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        env.close()


if __name__ == "__main__":
    main()
