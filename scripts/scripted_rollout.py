"""Run, record and score an explicitly SCRIPTED drawer baseline.

Stores observations at t and t+1, actions at t, and the initial simulator
state/XML for a later replay implementation. Does not download/train models.
"""
import argparse
import json
from pathlib import Path

from _windows_runtime import prepare_runtime
_runtime = prepare_runtime()


from pi05_cabinet.envs import add_scene_arguments, make_env_from_args
from pi05_cabinet.scripted import DrawerScript, FeedbackDrawerScript
from pi05_cabinet.recording import EpisodeRecorder, label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_scene_arguments(parser)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--controller", choices=("fixed_v2", "feedback_v4"), default="fixed_v2",
                        help="Opt-in feedback gates; fixed_v2 preserves the historical collector")
    parser.add_argument("--output", type=Path, required=True, help="New directory; never overwrite an episode")
    args = parser.parse_args()
    env = make_env_from_args(args)
    recorder = None
    try:
        obs = env.reset()
        plan = (FeedbackDrawerScript if args.controller == "feedback_v4" else DrawerScript)(env)
        recorder = EpisodeRecorder(args.output, env, obs, task=args.task, seed=args.seed,
            mode="SCRIPTED_PRIVILEGED_STATE",
            source="pose servo uses simulator handle pose; robot motion only through env.step",
            extra={"controller_revision": plan.revision,
                   "script_stages": [{"name": name, "target_xyz": target.tolist(), "gripper": grip, "steps": steps}
                                      for name, target, grip, steps in plan.stages]})
        for stage, action in plan.actions():
            obs, reward, done, _ = env.step(action)
            recorder.append(action, obs, stage, reward, done)
        extra = {}
        if isinstance(plan, FeedbackDrawerScript):
            recorder.metadata["controller_execution"] = plan.execution
            recorder.file.attrs["metadata_json"] = json.dumps(recorder.metadata)
            extra["controller_execution"] = plan.execution
        print(json.dumps(recorder.finish(extra), indent=2))
    finally:
        if recorder:
            recorder.abort("Interrupted scripted recording")
        env.close()


if __name__ == "__main__":
    main()
