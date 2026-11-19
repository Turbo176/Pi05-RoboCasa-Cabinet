"""Convert our completed raw episodes using the official LeRobot v0.4.4 API.

No upload or model download. Image features use lossless PNG embedded in
Parquet, avoiding lossy-video pixel mismatch during the first data validation.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

# Any missing local metadata must fail rather than fetch a remote dataset.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

import h5py
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from pi05_cabinet.adapters import (ACTION_NAMES, IMAGE_KEYS, SCHEMA_VERSION, STATE_NAMES,
                                    image_keys, policy_action, policy_observation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episodes", type=Path, nargs="+", help="Completed episode.hdf5 files in desired order")
    parser.add_argument("--output", type=Path, required=True, help="New directory")
    parser.add_argument("--repo-id", default="local/pi05-cabinet-pilot", help="Local identifier only; never pushed")
    parser.add_argument("--allow-scripted", action="store_true", help="Permit privileged scripted data for pipeline verification")
    args = parser.parse_args()
    if importlib.metadata.version("lerobot") != "0.4.4":
        raise RuntimeError("Use the pinned data CPU environment (lerobot==0.4.4)")
    if args.output.exists():
        raise FileExistsError(args.output)
    resolved = [p.resolve(strict=True) for p in args.episodes]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Duplicate input episode")
    provenance, total = [], 0
    for path in resolved:
        with h5py.File(path, "r") as file:
            meta = json.loads(file.attrs["metadata_json"])
            mode = meta["policy_mode"]
            if mode != "KEYBOARD_TELEOP" and not (args.allow_scripted and mode == "SCRIPTED_PRIVILEGED_STATE"):
                raise ValueError(f"Disallowed data source {mode}: {path}")
            if path.name != "episode.hdf5" or not file.attrs.get("complete", True):
                raise ValueError("Only completed episodes can be converted")
            n = len(file["actions"])
            camera_mapping = image_keys(file["observations"])
            if n < 1 or any(len(v) != n+1 for v in file["observations"].values()):
                raise ValueError("Invalid T / T+1 alignment")
            if meta["control_hz"] != 20 or not np.allclose(np.diff(file["sim_time"][:]), .05, atol=1e-6):
                raise ValueError("Expected a uniform 20Hz simulation clock")
            if "opengl-bottom-left-rgb" not in meta["image_convention"]:
                raise ValueError("Unknown image orientation; refusing a blind flip")
            for action in file["actions"]:
                policy_action(action)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            provenance.append(dict(filename=path.parent.name+"/"+path.name, sha256=digest,
                mode=mode, task=meta["task_variant"], seed=meta["seed"], frames=n,
                camera_mapping=camera_mapping,
                language=meta["lang"], success_final=bool(file["success"][-1])))
            if "scene_parameters" in meta:
                provenance[-1].update(target_drawer=meta["target_drawer"], scene_parameters=meta["scene_parameters"],
                    non_target_max_drift=float(file["evaluation/non_target_max_drift"][-1]),
                    non_target_tolerance=meta["non_target_tolerance"])
            total += n
    if len({p["sha256"] for p in provenance}) != len(provenance):
        raise ValueError("Identical episode content was supplied more than once")
    if len({p["camera_mapping"]["observation.images.front"] for p in provenance}) != 1:
        raise ValueError("Do not mix legacy and cabinet-front camera profiles in one dataset")
    features = {
        "observation.state": dict(dtype="float32", shape=(9,), names=STATE_NAMES),
        "action": dict(dtype="float32", shape=(7,), names=ACTION_NAMES),
    }
    for key in IMAGE_KEYS:
        features[key] = dict(dtype="image", shape=(256, 256, 3), names=["height", "width", "channels"])
    dataset = LeRobotDataset.create(repo_id=args.repo_id, root=args.output.resolve(), fps=20,
        robot_type="PandaOmron", features=features, use_videos=False,
        image_writer_processes=0, image_writer_threads=2, video_backend="pyav")
    for path in resolved:
        with h5py.File(path, "r") as file:
            meta = json.loads(file.attrs["metadata_json"])
            camera_mapping = image_keys(file["observations"])
            for i, action in enumerate(file["actions"]):
                raw = {key:file["observations"][key][i] for key in
                       ["robot0_joint_pos", "robot0_gripper_qpos", *camera_mapping.values()]}
                frame = policy_observation(raw)
                frame.update(action=policy_action(action), task=meta["lang"])
                dataset.add_frame(frame)
            dataset.save_episode(parallel_encoding=False)
    dataset.finalize()
    # Reopen through the official loader, and compare every frame against its
    # raw source. This catches frame shifts, channel swaps, vertical flips,
    # language mixups, and unintended changes to action/state semantics.
    loaded = LeRobotDataset(args.repo_id, root=args.output.resolve(), video_backend="pyav")
    if len(loaded) != total or loaded.num_episodes != len(resolved):
        raise AssertionError("Official loader length mismatch")
    global_index = 0
    for path in resolved:
        with h5py.File(path, "r") as file:
            meta = json.loads(file.attrs["metadata_json"])
            camera_mapping = image_keys(file["observations"])
            for i, action in enumerate(file["actions"]):
                item = loaded[global_index]
                raw = {key:file["observations"][key][i] for key in
                       ["robot0_joint_pos", "robot0_gripper_qpos", *camera_mapping.values()]}
                expected = policy_observation(raw)
                np.testing.assert_allclose(item["observation.state"].numpy(), expected["observation.state"], atol=1e-7)
                np.testing.assert_allclose(item["action"].numpy(), policy_action(action), atol=1e-7)
                for key in IMAGE_KEYS:
                    pixels = np.rint(item[key].numpy().transpose(1, 2, 0)*255).astype(np.uint8)
                    np.testing.assert_array_equal(pixels, expected[key])
                assert item["task"] == meta["lang"]
                assert abs(item["timestamp"].item() - i/20) < 1e-4
                global_index += 1
    report = dict(schema_version=SCHEMA_VERSION, lerobot_version="0.4.4", dataset_format="v3.0",
        dataset_api="official LeRobotDataset.create/add_frame/save_episode/finalize and loader",
        frames=total, episodes=len(resolved), fps=20, state_dim=9, action_dim=7,
        cameras=list(IMAGE_KEYS), image_storage="lossless PNG embedded in Parquet",
        all_frames_compared=True, official_loader_passed=True,
        no_upload=True, learned_policy=False, source_episodes=provenance)
    (args.output / "conversion_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
