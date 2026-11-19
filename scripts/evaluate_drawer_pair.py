"""Audit a small recorded drawer-pair pilot without running a learned policy.

Recompute target/non-target success from raw measurements, score the same
actions under the opposite target, and check prompt-paired reset equality.
Counterfactual scoring here is offline task bookkeeping, not a VLA test.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


def score(fractions, target, behavior, tolerance):
    index = ("top", "bottom").index(target)
    other = 1 - index
    drift = np.maximum.accumulate(np.abs(fractions[1:, other]-fractions[0, other]))
    target_ok = fractions[1:, index] >= .95 if behavior == "open" else fractions[1:, index] <= .05
    return target_ok & (drift <= tolerance), float(drift[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episodes", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New directory for JSON and CSV")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    rows, groups = [], {}
    paths = [p.resolve(strict=True) for p in args.episodes]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate episode input")
    for path in paths:
        with h5py.File(path, "r") as file:
            meta = json.loads(file.attrs["metadata_json"])
            if path.name != "episode.hdf5" or not file.attrs.get("complete", False):
                raise ValueError(f"Incomplete recording: {path}")
            if meta["policy_mode"] != "SCRIPTED_PRIVILEGED_STATE":
                raise ValueError("This pilot audit is explicitly for scripted baseline recordings")
            if meta.get("scene_variant") != "stacked_pair_v1" or meta["drawer_names"] != ["top", "bottom"]:
                raise ValueError("Expected the versioned top/bottom drawer measurement contract")
            fractions = file["evaluation/drawer_open_fractions"][:]
            steps = len(file["actions"])
            if fractions.shape != (steps+1, 2) or not np.isfinite(fractions).all() or not 1 <= steps <= 600:
                raise ValueError("Invalid raw drawer measurements or episode exceeds 600-step budget")
            target, behavior = meta["target_drawer"], meta["lang"].split()[0].lower()
            if meta["lang"] != f"{behavior.capitalize()} the {target} drawer.":
                raise ValueError("Language and selected target disagree")
            success, drift = score(fractions, target, behavior, meta["non_target_tolerance"])
            np.testing.assert_array_equal(file["success"][:], success)
            stored_drift = file["evaluation/non_target_max_drift"][:]
            other = 1 - ("top", "bottom").index(target)
            np.testing.assert_allclose(stored_drift, np.maximum.accumulate(
                np.abs(fractions[1:, other]-fractions[0, other])), atol=1e-12)
            opposite = "bottom" if target == "top" else "top"
            wrong_success, wrong_drift = score(fractions, opposite, behavior, meta["non_target_tolerance"])
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            rows.append(dict(episode=path.parent.name, episode_sha256=digest, task=meta["task_variant"],
                language=meta["lang"], seed=meta["seed"], scene_offset=meta["scene_offset"],
                pair_layout=meta.get("pair_layout", "compact"), target=target,
                steps=steps, final_top_fraction=float(fractions[-1, 0]),
                final_bottom_fraction=float(fractions[-1, 1]), non_target_max_drift=drift,
                success_final=bool(success[-1]), success_stable_last_10=bool(steps>=10 and success[-10:].all()),
                wrong_target_success_final=bool(wrong_success[-1]), wrong_target_max_drift=wrong_drift))
            key = (meta["task_variant"], meta["seed"], tuple(meta["scene_offset"]), meta.get("pair_layout", "compact"))
            pair = groups.setdefault(key, {})
            if target in pair:
                raise ValueError(f"Repeated target in pilot condition: {key}")
            pair[target] = dict(state=file["initial_sim_state"][:], xml=file["model_xml"][()],
                images={name: file["observations"][name][0] for name in
                        ("robot0_agentview_left_image", "robot0_eye_in_hand_image")},
                base=meta["init_robot_base_pos"])
    reset_checks = []
    for (task, seed, offset, layout), pair in groups.items():
        if set(pair) != {"top", "bottom"}:
            raise ValueError(f"Missing opposite-prompt episode for {task}, seed={seed}, offset={offset}")
        top, bottom = pair["top"], pair["bottom"]
        state_error = float(np.max(np.abs(top["state"]-bottom["state"])))
        images_equal = all(np.array_equal(top["images"][name], bottom["images"][name]) for name in top["images"])
        equal = state_error == 0. and top["xml"] == bottom["xml"] and images_equal and top["base"] == bottom["base"]
        if not equal:
            raise AssertionError("Prompt changes must preserve the complete physical initialization and policy images")
        reset_checks.append(dict(task=task, seed=seed, scene_offset=list(offset),
            pair_layout=layout,
            max_initial_state_error=state_error, initial_dual_rgb_identical=images_equal,
            model_xml_identical=True, robot_base_position=top["base"], passed=True))
    summary = dict(mode="SCRIPTED_PRIVILEGED_STATE", learned_policy=False,
        evaluation_split="development_pilot; includes controller tuning conditions; not an OOD or VLA evaluation",
        counterfactual_method="Offline score the same measured trajectory under the opposite target prompt; no model inference",
        episode_count=len(rows), success_final_count=sum(row["success_final"] for row in rows),
        stable_success_count=sum(row["success_stable_last_10"] for row in rows),
        wrong_target_success_count=sum(row["wrong_target_success_final"] for row in rows),
        non_target_max_drift=max(row["non_target_max_drift"] for row in rows),
        control_hz=20, max_control_steps=600, non_target_tolerance=.05,
        prompt_paired_initialization_checks=reset_checks, episodes=rows)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (args.output / "episodes.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
