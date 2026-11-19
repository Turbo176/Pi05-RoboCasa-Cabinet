"""Append training conditions without replacing a frozen validation split.

Reuse the existing collector, selection, converter and chunk checks. Each raw
recording keeps its original collection-plan hash. No model or Hub access.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import random
import subprocess
import sys

from prepare_sft_data import (CASES, ROOT, check_chunks, digest, read_json,
                              validate_plan, write_new)


def local(path):
    return Path(path).resolve(strict=True).relative_to(ROOT).as_posix()


def reference(path):
    return dict(path=local(path), sha256=digest(path))


def verify_files(hashes):
    for name, expected in hashes.items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"Protected file changed: {name}")


def verify_validation(extension):
    root = ROOT / extension["validation_dataset"]
    actual = {local(p) for p in root.rglob("*") if p.is_file()}
    expected = set(extension["validation_files_sha256"])
    if actual != expected:
        raise ValueError("The frozen validation file inventory changed")
    verify_files(extension["validation_files_sha256"])
    verify_files(extension["protected_files_sha256"])


def freeze(args):
    base = read_json(args.base_plan)
    manifest = read_json(args.base_manifest)
    report = read_json(args.base_report)
    validate_plan(base)
    if (manifest["plan_sha256"] != digest(args.base_plan) or
            report["selection_manifest_sha256"] != digest(args.base_manifest)):
        raise ValueError("Base plan, selection and report are not tied together")
    validation = ROOT / report["splits"]["validation"]["dataset"]
    if not report["splits"]["validation"]["official_all_frames_passed"]:
        raise ValueError("Base validation readback did not pass")
    verify_files(base["collection_code_sha256"])
    used = base["conditions"] + base.get("retired_collection_conditions", [])
    used += base.get("base_collection_conditions", [])
    if len(set(args.train_seeds)) != len(args.train_seeds) or any(
            s in {c["seed"] for c in used} for s in args.train_seeds):
        raise ValueError("Supplement seeds must be fresh and unique")
    positions = {tuple(c["scene_offset"]) for c in used}
    rng = random.Random(args.sampler_seed)
    last_id = max(int(c["id"].split("_")[-1]) for c in base["conditions"] if c["split"] == "train")
    conditions = []
    for i, seed in enumerate(args.train_seeds, last_id + 1):
        xy = [round(rng.uniform(-.04, .04), 4) for _ in range(2)]
        if tuple(xy) in positions:
            raise ValueError("Repeated offset; choose a new sampler seed before collection")
        positions.add(tuple(xy))
        conditions.append(dict(id=f"train_{i:03d}", split="train", seed=seed,
                               scene_offset=xy, run_now=True))
    tests = [deepcopy(c) for c in base["conditions"] if not c["run_now"]]
    protected = {local(p): digest(p) for p in (args.base_plan, args.base_manifest, args.base_report)}
    for row in manifest["episodes"]:
        if digest(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("Base raw episode no longer matches its selection")
        protected[row["path"]] = row["sha256"]
    plan = deepcopy(base)
    plan.pop("previous_plan", None)
    plan.update(created_utc=datetime.now(timezone.utc).isoformat(),
        purpose="Training-only supplement; retain the base validation and all reserved tests",
        sampler=f"Python random.Random({args.sampler_seed}); no outcome-based resampling",
        legacy_rule="Earlier retired conditions remain excluded; v4 base candidates are retained by source hash",
        base_collection_conditions=[c for c in base["conditions"] if c["run_now"]],
        conditions=conditions + tests,
        extension=dict(schema="cabinet_training_extension_v1", base_plan=reference(args.base_plan),
            base_manifest=reference(args.base_manifest), base_report=reference(args.base_report),
            validation_dataset=local(validation),
            validation_files_sha256={local(p): digest(p) for p in sorted(validation.rglob("*")) if p.is_file()},
            protected_files_sha256=protected,
            rule="Append train only; preserve original per-episode plans, validation bytes and reserved tests"))
    plan["collection_code_sha256"][local(__file__)] = digest(__file__)
    validate_plan(plan)
    write_new(args.output, plan)
    print(dict(plan=str(args.output), sha256=digest(args.output), new_conditions=conditions,
               frozen_validation_files=len(plan["extension"]["validation_files_sha256"]),
               reserved_test_conditions=len(tests)))


def merge(args):
    plan = read_json(args.plan)
    validate_plan(plan)
    extension = plan["extension"]
    verify_validation(extension)
    verify_files(plan["collection_code_sha256"])
    base_plan = read_json(ROOT / extension["base_plan"]["path"])
    if [c for c in plan["conditions"] if not c["run_now"]] != [
            c for c in base_plan["conditions"] if not c["run_now"]]:
        raise ValueError("Reserved tests were modified")
    base = read_json(ROOT / extension["base_manifest"]["path"])
    base_report = read_json(ROOT / extension["base_report"]["path"])
    supplement = read_json(args.supplement_manifest)
    supplement_report = read_json(args.supplement_report)
    if (supplement["plan_sha256"] != digest(args.plan) or
            supplement_report["selection_manifest_sha256"] != digest(args.supplement_manifest) or
            supplement_report["plan_sha256"] != digest(args.plan)):
        raise ValueError("Supplement collection, selection and report hashes disagree")
    expected = {(c["id"], case) for c in plan["conditions"] if c["run_now"] for case in CASES}
    if (len(supplement["episodes"]) != len(expected) or
            {(r["condition_id"], r["case"]) for r in supplement["episodes"]} != expected or
            any(r["split"] != "train" for r in supplement["episodes"])):
        raise ValueError("Supplement must retain every planned training attempt")
    if not supplement_report["splits"]["train"].get("official_all_frames_passed"):
        raise ValueError("Supplement official readback did not pass")
    if args.output.exists() or args.report.exists():
        raise FileExistsError("Use new output and report paths")
    rows = []
    seen = {key: {} for key in ("sha256", "initial_state_sha256", "initial_dual_rgb_sha256")}
    for source in (base, supplement):
        for original in source["episodes"]:
            row = deepcopy(original)
            row["collection_plan_sha256"] = source["plan_sha256"]
            if digest(ROOT / row["path"]) != row["sha256"]:
                raise ValueError("Source episode changed")
            for key, table in seen.items():
                value = row[key]
                if value in table and (key == "sha256" or table[value] != row["split"]):
                    raise ValueError(f"Duplicate episode or cross-split reset leakage: {key}")
                table[value] = row["split"]
            rows.append(row)
    train = [r for r in rows if r["split"] == "train" and r["selected"]]
    if not train:
        raise ValueError("No eligible training episodes")
    manifest = dict(schema="cabinet_sft_union_v1", source="SCRIPTED_PRIVILEGED_STATE", learned_policy=False,
        policy_schema=base["policy_schema"], merge_code_sha256=digest(__file__),
        plans=[extension["base_plan"], reference(args.plan)],
        parent_selections=[extension["base_manifest"], reference(args.supplement_manifest)],
        attempted_episodes=len(rows), selected_episodes=sum(r["selected"] for r in rows),
        human_visual_acceptance="pending", episodes=rows)
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "selection_manifest.json", manifest)
    output = args.output / "train"
    subprocess.run([sys.executable, str(ROOT / "scripts/convert_lerobot.py"),
        *[str(ROOT / row["path"]) for row in train], "--allow-scripted", "--output", str(output)],
        cwd=ROOT, check=True)
    conversion = read_json(output / "conversion_report.json")
    if [r["sha256"] for r in train] != [s["sha256"] for s in conversion["source_episodes"]]:
        raise ValueError("Converter reordered the union")
    chunks = check_chunks(output, train)
    verify_validation(extension)
    summary = dict(schema="cabinet_training_extension_report_v1", source="SCRIPTED_PRIVILEGED_STATE",
        learned_policy=False, extension_plan=reference(args.plan),
        selection_manifest=reference(args.output / "selection_manifest.json"),
        parent_reports=[extension["base_report"], reference(args.supplement_report)],
        attempted_episodes=len(rows), selected_episodes=sum(r["selected"] for r in rows),
        stable_success_count=sum(r["stable_success"] for r in rows),
        supplemental_attempts=len(supplement["episodes"]),
        supplemental_stable_successes=sum(r["stable_success"] for r in supplement["episodes"]),
        splits=dict(train=dict(dataset=output.relative_to(ROOT).as_posix(),
            attempted=sum(r["split"] == "train" for r in rows), selected=len(train),
            rejected=sum(r["split"] == "train" and not r["selected"] for r in rows),
            frames=sum(r["frames"] for r in train),
            selected_prompt_counts=dict(Counter(r["language"] for r in train)),
            selected_prompt_spawn_side_counts=dict(Counter(
                r["language"] + " | robot=" + r["robot_side_of_cabinet_world_x"] for r in train)),
            official_all_frames_passed=bool(conversion["all_frames_compared"] and conversion["official_loader_passed"]),
            chunk_check=chunks), validation=base_report["splits"]["validation"]),
        validation_reused_byte_for_byte=True,
        validation_files_sha256=extension["validation_files_sha256"],
        protected_base_files_unchanged=True, train_validation_reset_hashes_disjoint=True,
        reserved_test_conditions_unexecuted=sum(not c["run_now"] for c in plan["conditions"]),
        train_normalization_stats=(output / "meta/stats.json").relative_to(ROOT).as_posix(),
        normalization_rule="Use the union train statistics for both splits; never validation statistics",
        max_replay_joint_error_rad=max(r["replay_max_joint_error_rad"] for r in rows),
        max_replay_drawer_error=max(r["replay_max_drawer_error"] for r in rows),
        non_target_max_drift=max(r["non_target_max_drift"] for r in rows),
        human_visual_acceptance="pending", sufficient_for_sft_quality_claim=False,
        limitations=["Scripted candidates require full-episode human inspection",
            "One validation initialization; no learned-policy metrics",
            "World translation is not a held-out robot-relative OOD region",
            "No model processors, weights, SFT or RL executed"],
        episode_results=[{k:v for k,v in r.items() if k != "collection_code_sha256"} for r in rows])
    write_new(args.report, summary)
    print(dict(report=str(args.report), train_episodes=len(train), train_frames=sum(r["frames"] for r in train),
               supplemental_attempts=len(supplement["episodes"]), validation_unchanged=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--base-plan", type=Path, required=True)
    plan.add_argument("--base-manifest", type=Path, required=True)
    plan.add_argument("--base-report", type=Path, required=True)
    plan.add_argument("--train-seeds", nargs="+", type=int, required=True)
    plan.add_argument("--sampler-seed", type=int, required=True)
    plan.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("merge")
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--supplement-manifest", type=Path, required=True)
    build.add_argument("--supplement-report", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    freeze(args) if args.command == "plan" else merge(args)


if __name__ == "__main__":
    main()
