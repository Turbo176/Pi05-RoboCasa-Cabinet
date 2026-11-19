"""Freeze a small collection plan; select successful, replayed SFT candidates.

Uses the existing recorder, audit and official converter. No model imports,
training, Hub access or public dataset downloads. Held-out tests stay unused.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "open_top": ("OpenDrawerPairLite", "Open the top drawer."),
    "open_bottom": ("OpenDrawerPairLite", "Open the bottom drawer."),
    "close_top": ("CloseDrawerPairLite", "Close the top drawer."),
    "close_bottom": ("CloseDrawerPairLite", "Close the bottom drawer."),
}
COLLECTION_FILES = [
    "src/pi05_cabinet/envs.py", "src/pi05_cabinet/scripted.py",
    "src/pi05_cabinet/recording.py", "src/pi05_cabinet/adapters.py",
    "scripts/_windows_runtime.py", "scripts/scripted_rollout.py",
    "scripts/replay_episode.py", "scripts/evaluate_drawer_pair.py",
    "scripts/run_pair_pilot.ps1", "requirements/sim-win.lock.txt",
]


def digest(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, indent=2, allow_nan=False)
        file.write("\n")


def freeze_plan(args):
    rng = random.Random(args.sampler_seed)
    conditions = []
    previous = read_json(args.previous_plan) if args.previous_plan else None
    if previous:
        validate_plan(previous)
        previous_seeds = {c["seed"] for c in previous["conditions"]}
        if previous_seeds.intersection(args.train_seeds + args.validation_seeds):
            raise ValueError("New training/validation conditions must use fresh seeds after controller tuning")
    splits = [("train", args.train_seeds), ("validation", args.validation_seeds)]
    if not previous:
        splits.extend([("test_id", range(1001, 1021)), ("test_translation", range(2001, 2021))])
    for split, seeds in splits:
        for i, seed in enumerate(seeds, 1):
            dx, dy = [round(rng.uniform(-.04, .04), 4) for _ in range(2)]
            if split == "test_translation":
                dx = round(rng.uniform(.08, .12) * (-1 if i % 2 else 1), 4)
            conditions.append(dict(id=f"{split}_{i:03d}", split=split, seed=seed,
                scene_offset=[dx, dy], run_now=split in ("train", "validation")))
    if previous:
        retired_positions = {tuple(c["scene_offset"]) for c in previous["conditions"] if c["run_now"]}
        if any(tuple(c["scene_offset"]) in retired_positions for c in conditions):
            raise ValueError("New conditions repeat a retired initialization position")
        # Keep the unexecuted test inventory exactly as frozen, rather than
        # silently resampling tests when a development failure is repaired.
        conditions.extend(c for c in previous["conditions"] if not c["run_now"])
    plan = dict(schema="cabinet_split_plan_v1", created_utc=datetime.now(timezone.utc).isoformat(),
        purpose="Data readiness pilot; too small for a model quality claim",
        sampler=f"Python random.Random({args.sampler_seed}); reserved tests inherited if previous_plan is set",
        pair_layout="spaced", source="SCRIPTED_PRIVILEGED_STATE", learned_policy=False,
        prompts=list(CASES.values()), max_control_steps=600, fps=20,
        group_rule="All four commands of one seed/offset/layout stay in one split; seeds are disjoint across splits",
        legacy_rule="All pre-plan episodes, including tuned seed 0/1 conditions, are development-only and excluded",
        regions_m=dict(train_validation_test_id=dict(dx=[-.04, .04], dy=[-.04, .04]),
            test_translation=dict(abs_dx=[.08, .12], dy=[-.04, .04])),
        translation_claim_limit="World cabinet translation stress test only; upstream spawn moves with cabinet. Not a held-out robot-relative position region.",
        relative_position_ood_status="Not yet specified or implemented; must freeze a new relative-position protocol before collecting or claiming it",
        test_rule="Do not execute reserved tests or convert them to SFT; if used for tuning, retire this test version",
        collection_code_sha256={name: digest(ROOT / name) for name in COLLECTION_FILES}, conditions=conditions)
    if previous:
        plan.update(previous_plan=dict(path=args.previous_plan.as_posix(), sha256=digest(args.previous_plan)),
            retired_collection_conditions=[c for c in previous["conditions"] if c["run_now"]],
            legacy_rule="All previous-plan collection conditions and earlier tuning conditions are excluded from this new collection")
    validate_plan(plan)
    write_new(args.output, plan)
    print(json.dumps(dict(plan=str(args.output), sha256=digest(args.output),
        run_now=[c for c in conditions if c["run_now"]],
        reserved_conditions=sum(not c["run_now"] for c in conditions)), indent=2))


def validate_plan(plan):
    if plan["schema"] != "cabinet_split_plan_v1" or plan["pair_layout"] != "spaced":
        raise ValueError("Unknown collection plan")
    ids, seeds, positions = set(), set(), set()
    for condition in plan["conditions"]:
        split, seed, xy = condition["split"], condition["seed"], condition["scene_offset"]
        if split not in ("train", "validation", "test_id", "test_translation"):
            raise ValueError("Unrecognized split")
        if condition["id"] in ids or seed in seeds or tuple(xy) in positions or seed < 100:
            raise ValueError("Repeated condition/seed/position or legacy development seed")
        if len(xy) != 2 or not all(abs(v) <= .15 for v in xy):
            raise ValueError("Invalid scene offset")
        low, high = (.08, .12) if split == "test_translation" else (0., .04)
        if not low <= abs(xy[0]) <= high or abs(xy[1]) > .04:
            raise ValueError("Condition lies outside its split's fixed region")
        if condition["run_now"] != (split in ("train", "validation")):
            raise ValueError("Held-out test cannot be part of pilot collection")
        ids.add(condition["id"])
        seeds.add(seed)
        positions.add(tuple(xy))


def inspect_episode(path, condition, case, audit_row, replay, code_hashes):
    import h5py
    import numpy as np
    from evaluate_drawer_pair import score
    from pi05_cabinet.adapters import IMAGE_KEYS, policy_action, policy_observation

    sha = digest(path)
    if sha != audit_row["episode_sha256"] or sha != replay.get("source_episode_sha256"):
        raise ValueError("Independent audit/replay is not tied to this exact episode hash")
    task, prompt = CASES[case]
    with h5py.File(path, "r") as file:
        meta = json.loads(file.attrs["metadata_json"])
        if not file.attrs.get("complete", False) or path.name != "episode.hdf5":
            raise ValueError("Incomplete episode")
        if (meta["task_variant"], meta["lang"], meta["seed"], meta["policy_mode"]) != (
                task, prompt, condition["seed"], "SCRIPTED_PRIVILEGED_STATE"):
            raise ValueError("Episode does not match its assigned condition, prompt or source")
        if meta["scene_offset"] != condition["scene_offset"] or meta["pair_layout"] != "spaced":
            raise ValueError("Scene differs from the frozen plan")
        if meta["schema_version"] != "cabinet_raw_v1" or meta["drawer_names"] != ["top", "bottom"]:
            raise ValueError("Unknown raw/paired data schema")
        n = len(file["actions"])
        if not 10 <= n <= 600 or any(len(v) != n+1 for v in file["observations"].values()):
            raise ValueError("Invalid T/T+1 alignment or control budget")
        if meta["control_hz"] != 20 or not np.allclose(np.diff(file["sim_time"][:]), .05, atol=1e-6):
            raise ValueError("Invalid control clock")
        if "opengl-bottom-left-rgb" not in meta["image_convention"]:
            raise ValueError("Unknown RGB convention")
        fractions = file["evaluation/drawer_open_fractions"][:]
        if fractions.shape != (n+1, 2) or not np.isfinite(fractions).all():
            raise ValueError("Invalid measured drawer states")
        if meta["non_target_tolerance"] != .05:
            raise ValueError("The fixed non-target threshold was changed")
        success, drift = score(fractions, meta["target_drawer"], prompt.split()[0].lower(), .05)
        np.testing.assert_array_equal(file["success"][:], success)
        other = 1-("top", "bottom").index(meta["target_drawer"])
        np.testing.assert_allclose(file["evaluation/non_target_max_drift"][:],
            np.maximum.accumulate(np.abs(fractions[1:, other]-fractions[0, other])), atol=1e-12)
        for i, action in enumerate(file["actions"]):
            policy_action(action)
            policy_observation({key: file["observations"][key][i] for key in
                ["robot0_joint_pos", "robot0_gripper_qpos", *IMAGE_KEYS.values()]})
        # Joint state alone omits fixture geometry and the robot's model pose.
        initial_hash = hashlib.sha256(file["model_xml"][()] +
            file["initial_sim_state"][:].tobytes()).hexdigest()
        visual_hash = hashlib.sha256(b"".join(file["observations"][key][0].tobytes()
            for key in IMAGE_KEYS.values())).hexdigest()
        spawn = meta["init_robot_base_pos"]
        relative = [1+meta["scene_offset"][0]-spawn[0], meta["scene_offset"][1]-spawn[1]]
        final, stable = bool(success[-1]), bool(success[-10:].all())
        if (final, stable) != (audit_row["success_final"], audit_row["success_stable_last_10"]):
            raise ValueError("Audit success disagrees with raw measurements")
        replay_ok = (replay.get("mode") == "RECORDED_ACTION_REPLAY" and replay.get("replay_within_tolerance") is True
            and replay["steps"] == n and replay["task"] == task and replay["seed"] == condition["seed"]
            and replay["initial_state_max_error"] <= 1e-8
            and replay["max_joint_error_rad"] < .01 and replay["max_all_drawer_fraction_error"] < .01
            and bool(replay["success_final"]) == final)
        reasons = []
        if not final: reasons.append("task_final_failure")
        if not stable: reasons.append("not_successful_for_final_10_steps")
        if drift > .05: reasons.append("non_target_drawer_moved")
        if not replay_ok: reasons.append("action_replay_failed")
        return dict(condition_id=condition["id"], split=condition["split"], case=case,
            path=path.relative_to(ROOT).as_posix(), sha256=sha, frames=n,
            source=meta["policy_mode"], language=prompt, seed=condition["seed"],
            scene_offset=condition["scene_offset"], robot_spawn_world_m=spawn,
            robot_spawn_world_euler_rad=meta["init_robot_base_ori"],
            robot_side_of_cabinet_world_x="left" if relative[0] > 0 else "right",
            cabinet_minus_robot_spawn_world_xy_m=relative, initial_state_sha256=initial_hash,
            initial_dual_rgb_sha256=visual_hash, success_final=final, stable_success=stable,
            non_target_max_drift=drift, replay_passed=bool(replay_ok),
            replay_max_joint_error_rad=replay["max_joint_error_rad"],
            replay_max_drawer_error=replay["max_all_drawer_fraction_error"],
            selected=not reasons, rejection_reasons=reasons,
            collection_code_sha256=code_hashes)


def check_chunks(dataset_root, sources, chunk_size=50):
    """Exercise official episode-boundary padding with actual data, no model."""
    import h5py
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from pi05_cabinet.adapters import policy_action
    from torch.utils.data import DataLoader, Subset
    loaded = LeRobotDataset("local/pi05-cabinet-sft-pilot", root=dataset_root.resolve(),
        delta_timestamps={"action": [i/20 for i in range(chunk_size)]}, video_backend="pyav")
    offset, checked, starts = 0, 0, []
    for episode_index, source in enumerate(sources):
        starts.append(offset)
        with h5py.File(ROOT / source["path"], "r") as file:
            actions = np.stack([policy_action(action) for action in file["actions"]])
        n = len(actions)
        # Interior, last full chunk, first padded chunk and final frame; include
        # every episode transition, where accidental cross-episode chunks leak.
        for i in sorted({0, n//2, n-chunk_size, n-chunk_size+1, n-1}):
            sample = loaded[offset+i]
            indices = np.minimum(np.arange(i, i+chunk_size), n-1)
            np.testing.assert_allclose(sample["action"].numpy(), actions[indices], atol=1e-7)
            np.testing.assert_array_equal(sample["action_is_pad"].numpy(), np.arange(i, i+chunk_size) >= n)
            assert sample["action"].shape == (chunk_size, 7)
            assert sample["observation.state"].shape == (9,) and sample["episode_index"].item() == episode_index
            assert sample["task"] == source["language"]
            checked += 1
        offset += n
    batch_size = min(4, len(starts))
    batch = next(iter(DataLoader(Subset(loaded, starts), batch_size=batch_size, num_workers=0)))
    assert list(batch["action"].shape) == [batch_size, chunk_size, 7]
    assert list(batch["action_is_pad"].shape) == [batch_size, chunk_size]
    assert list(batch["observation.state"].shape) == [batch_size, 9]
    assert list(batch["task"]) == [source["language"] for source in sources[:batch_size]]
    for key in ("observation.images.front", "observation.images.wrist"):
        assert list(batch[key].shape) == [batch_size, 3, 256, 256]
    stats = loaded.meta.stats
    vector_stats = {}
    for key, size in (("observation.state", 9), ("action", 7)):
        values = stats[key]
        for name in ("min", "max", "mean", "std", "q01", "q99"):
            assert np.asarray(values[name]).shape == (size,) and np.isfinite(values[name]).all()
        vector_stats[key] = {name: np.asarray(values[name]).tolist()
                            for name in ("min", "max", "mean", "std", "q01", "q99")}
    return dict(chunk_size=chunk_size, action_shape=[chunk_size, 7], boundary_samples_checked=checked,
        official_action_padding_passed=True, cross_episode_actions_observed=False,
        cpu_batch_action_shape=list(batch["action"].shape), cpu_batch_state_shape=list(batch["observation.state"].shape),
        cpu_batch_rgb_shape=list(batch["observation.images.front"].shape), cpu_batch_language_passed=True,
        stats_sha256=digest(dataset_root / "meta/stats.json"), vector_stats=vector_stats)


def build_datasets(args):
    plan = read_json(args.plan)
    validate_plan(plan)
    if args.output.exists() or args.report.exists():
        raise FileExistsError("Dataset root and report must both be new")
    plan_hash, rows = digest(args.plan), []
    for condition in plan["conditions"]:
        directory = args.raw_root / condition["id"]
        if not condition["run_now"]:
            if directory.exists():
                raise ValueError("A reserved test directory exists in the collection root")
            continue
        request = read_json(directory / "collection_request.json")
        if request["plan_sha256"] != plan_hash or request["condition_id"] != condition["id"]:
            raise ValueError("Collection was not requested with this exact pre-recording plan")
        audit = read_json(directory / "evaluation/report.json")
        if len(audit["episodes"]) != 4 or len(audit["prompt_paired_initialization_checks"]) != 2:
            raise ValueError("All four prompts and both paired reset checks are required")
        if not all(c["passed"] for c in audit["prompt_paired_initialization_checks"]):
            raise ValueError("Changing the target prompt changed the initial state")
        audit_rows = {row["episode"]: row for row in audit["episodes"]}
        for case in CASES:
            path = (directory / case / "episode.hdf5").resolve(strict=True)
            replay = read_json(directory / f"replay_{case}/report.json")
            rows.append(inspect_episode(path, condition, case, audit_rows[case], replay,
                plan["collection_code_sha256"]))
    # Deduplicate by raw bytes and physical/visual initialization across splits.
    # Top/bottom intentionally share resets within a split, never across them.
    seen = {key: {} for key in ("sha256", "initial_state_sha256", "initial_dual_rgb_sha256")}
    for row in rows:
        for key, table in seen.items():
            value = row[key]
            if value in table and (key == "sha256" or table[value] != row["split"]):
                raise ValueError(f"Duplicate episode or cross-split reset leakage: {key}")
            table[value] = row["split"]
    args.output.mkdir(parents=True, exist_ok=False)
    # Save selection before conversion so a failed converter remains auditable.
    manifest = dict(schema="cabinet_sft_selection_v1", plan_sha256=plan_hash,
        selection_code_sha256=digest(__file__), source="SCRIPTED_PRIVILEGED_STATE",
        policy_schema="pandaomron_arm_osc_v1", learned_policy=False,
        rules=["completed raw schema", "600-step budget", "last 10 steps successful",
               "non-target drift <=0.05", "same-source-hash replay passed", "disjoint initialization groups"],
        attempted_episodes=len(rows), selected_episodes=sum(row["selected"] for row in rows), episodes=rows)
    write_new(args.output / "selection_manifest.json", manifest)
    summaries = {}
    for split in ("train", "validation"):
        attempted = [row for row in rows if row["split"] == split]
        selected = [row for row in attempted if row["selected"]]
        summary = dict(attempted=len(attempted), selected=len(selected),
            rejected=len(attempted)-len(selected), frames=sum(row["frames"] for row in selected),
            selected_prompt_counts=dict(Counter(row["language"] for row in selected)),
            selected_prompt_spawn_side_counts=dict(Counter(
                row["language"] + " | robot=" + row["robot_side_of_cabinet_world_x"] for row in selected)),
            all_four_prompts_present=len({row["language"] for row in selected}) == 4)
        if selected:
            output = args.output / split
            subprocess.run([sys.executable, str(ROOT / "scripts/convert_lerobot.py"),
                *[str(ROOT / row["path"]) for row in selected], "--allow-scripted", "--output", str(output)],
                cwd=ROOT, check=True)
            conversion = read_json(output / "conversion_report.json")
            assert [row["sha256"] for row in selected] == [s["sha256"] for s in conversion["source_episodes"]]
            summary.update(dataset=output.resolve().relative_to(ROOT).as_posix(),
                official_all_frames_passed=conversion["all_frames_compared"] and conversion["official_loader_passed"],
                chunk_check=check_chunks(output, selected))
        summaries[split] = summary
    report = dict(schema="cabinet_data_readiness_report_v1", source="SCRIPTED_PRIVILEGED_STATE", learned_policy=False,
        plan_sha256=plan_hash, selection_manifest_sha256=digest(args.output / "selection_manifest.json"),
        selection_manifest=(args.output / "selection_manifest.json").resolve().relative_to(ROOT).as_posix(),
        attempted_episodes=len(rows), selected_episodes=manifest["selected_episodes"],
        stable_success_count=sum(row["stable_success"] for row in rows),
        max_replay_joint_error_rad=max(row["replay_max_joint_error_rad"] for row in rows),
        max_replay_drawer_error=max(row["replay_max_drawer_error"] for row in rows),
        non_target_max_drift=max(row["non_target_max_drift"] for row in rows),
        splits=summaries, reserved_test_conditions_unexecuted=sum(not c["run_now"] for c in plan["conditions"]),
        train_normalization_stats=(args.output / "train/meta/stats.json").resolve().relative_to(ROOT).as_posix()
            if summaries["train"]["selected"] else None,
        normalization_rule="Use only the train stats for both training and validation; validation's own conversion stats are diagnostic only",
        train_validation_reset_hashes_disjoint=True, successful_demonstration_candidates_only=True,
        sufficient_for_sft_quality_claim=False, human_visual_acceptance="pending",
        limitations=[f"{sum(c['split'] == 'train' for c in plan['conditions'])} train conditions and "
                    f"{sum(c['split'] == 'validation' for c in plan['conditions'])} validation conditions only; expand after quality inspection",
            "Privileged scripted actions are not human demonstrations or pi0.5 rollouts",
            "Validation inspected for data readiness; if used to tune controller, mark it development and version the split",
            "Translation tests unexecuted; no reserved robot-relative OOD region implemented",
            "No weights, tokenizer, processor, forward/backward or model rollout validated"],
        episode_results=[{k:v for k,v in row.items() if k != "collection_code_sha256"} for row in rows])
    write_new(args.report, report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Freeze deterministic conditions before simulation")
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--previous-plan", type=Path,
                      help="Retire earlier collection conditions and retain its unexecuted test inventory")
    plan.add_argument("--train-seeds", nargs="+", type=int, default=[101, 102])
    plan.add_argument("--validation-seeds", nargs="+", type=int, default=[201])
    plan.add_argument("--sampler-seed", type=int, default=20261119)
    build = commands.add_parser("build", help="Audit successes and build separate official train/validation datasets")
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--raw-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    freeze_plan(args) if args.command == "plan" else build_datasets(args)


if __name__ == "__main__":
    main()
