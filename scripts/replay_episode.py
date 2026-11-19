"""Replay recorded actions in the identical Lite scene and quantify drift."""
import argparse
import hashlib
import json
from pathlib import Path

from _windows_runtime import prepare_runtime
_runtime = prepare_runtime()

import h5py
import imageio.v2 as imageio
import mujoco
import numpy as np
from pi05_cabinet.envs import make_lite_env
from pi05_cabinet.recording import label


def contact_sample(env, obs, step, stage):
    """Read contacts after a control step; do not alter the simulated state.

    Samples cover the final physics substep of each 20 Hz action, not every
    internal integration step. Forces use MuJoCo's contact-local frame.
    """
    contacts = []
    for index in range(env.sim.data.ncon):
        contact = env.sim.data.contact[index]
        names = [env.sim.model.geom_id2name(int(geom)) or "" for geom in (contact.geom1, contact.geom2)]
        robot = lambda name: name.startswith(("robot0_", "gripper0_"))
        if not any(robot(name) for name in names) or all(robot(name) for name in names):
            continue
        force = np.zeros(6)
        mujoco.mj_contactForce(env.sim.model._model, env.sim.data._data, index, force)
        contacts.append(dict(geoms=names, distance_m=float(contact.dist),
            position_world_m=contact.pos.tolist(), force_contact_frame_n=force[:3].tolist(),
            force_norm_n=float(np.linalg.norm(force[:3]))))
    handle = f"{env.drawer.name}_door_handle_handle"
    return dict(step=step, stage=stage, sim_time_s=float(env.sim.data.time),
        target_fraction=float(env.drawer.get_door_state(env=env)["door"]),
        eef_world_m=obs["robot0_eef_pos"].tolist(),
        gripper_qpos_m=obs["robot0_gripper_qpos"].tolist(),
        finger_pad_centres_world_m=[env.sim.data.get_geom_xpos(
            f"gripper0_right_finger{finger}_pad_collision").tolist() for finger in (1, 2)],
        handle_world_m=env.sim.data.get_geom_xpos(handle).tolist(), contacts=contacts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contact-diagnostics", action="store_true",
                        help="Save read-only 20 Hz robot/fixture contact and gripper samples")
    args = parser.parse_args()
    with args.episode.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    with h5py.File(args.episode, "r") as file:
        if args.episode.name != "episode.hdf5" or not file.attrs.get("complete", True):
            raise ValueError("Replay requires a completed episode.hdf5")
        meta = json.loads(file.attrs["metadata_json"])
        actions = file["actions"][:]
        stages = file["stage"].asstr()[:] if args.contact_diagnostics else None
        joint_positions = file["observations/robot0_joint_pos"][:]
        fractions = file["drawer_open_fraction"][:]
        all_fractions = file["evaluation/drawer_open_fractions"][:] if "evaluation" in file else None
        initial_state = file["initial_sim_state"][:]
        stored_xml = file["model_xml"][()].decode() if "model_xml" in file else file.attrs["model_xml"]
    env = make_lite_env(meta["task_variant"], meta["seed"], **meta.get("scene_parameters", {}))
    joint_error, fraction_error, all_fraction_error = 0., 0., 0.
    contact_samples = []
    try:
        env.reset()
        if env.sim.model.get_xml() != stored_xml:
            raise ValueError("Scene XML differs; use the recorded code/assets and dependency versions")
        reset_error = float(np.max(np.abs(env.sim.get_state().flatten()-initial_state)))
        if reset_error > 1e-8:
            raise ValueError(f"Seeded reset differs from saved initial state: {reset_error}")
        # Restore captured time/qpos/qvel. MjSimState is not a complete snapshot
        # of all MuJoCo integrator caches; replay drift is measured explicitly.
        env.sim.set_state_from_flattened(initial_state)
        env.sim.forward()
        with imageio.get_writer(args.output / "replay.mp4", fps=20, codec="libx264") as writer:
            for i, action in enumerate(actions):
                obs, _, _, _ = env.step(action)
                opening = float(env.drawer.get_door_state(env=env)["door"])
                joint_error = max(joint_error, float(np.max(np.abs(obs["robot0_joint_pos"]-joint_positions[i+1]))))
                fraction_error = max(fraction_error, abs(opening-fractions[i]))
                metrics = env.task_metrics() if hasattr(env, "task_metrics") else None
                if args.contact_diagnostics:
                    contact_samples.append(contact_sample(env, obs, i + 1, str(stages[i])))
                if all_fractions is not None:
                    all_fraction_error = max(all_fraction_error, float(np.max(np.abs(
                        np.array(list(metrics["drawer_fractions"].values()))-all_fractions[i+1]))))
                rgb = env.sim.render(width=640, height=480, camera_name="cabinet_overview")[::-1].copy()
                writer.append_data(label(rgb, meta["task_variant"], meta["seed"], "ACTION_REPLAY", opening,
                    env._check_success(), mode="REPLAY | " + meta["policy_mode"],
                    instruction=meta["lang"] if metrics else None, task_metrics=metrics))
        report = dict(mode="RECORDED_ACTION_REPLAY", source_policy_mode=meta["policy_mode"], learned_policy=False,
            source_episode_sha256=source_hash,
            task=meta["task_variant"], seed=meta["seed"], steps=len(actions),
            initial_state_max_error=reset_error, max_joint_error_rad=joint_error,
            max_open_fraction_error=float(fraction_error), success_final=bool(env._check_success()),
            replay_within_tolerance=bool(joint_error<.01 and fraction_error<.01 and all_fraction_error<.01))
        if all_fractions is not None:
            report.update(max_all_drawer_fraction_error=all_fraction_error, **env.task_metrics())
            report["scene_parameters"] = meta["scene_parameters"]
        if args.contact_diagnostics:
            diagnostic = dict(schema="cabinet_contact_diagnostics_v1", source_episode_sha256=source_hash,
                source_policy_mode=meta["policy_mode"], learned_policy=False,
                sampling="Final physics substep of each 20 Hz control action; transient contacts may be missed",
                force_frame="MuJoCo contact-local; first three mj_contactForce components, newtons",
                samples=contact_samples)
            (args.output / "contacts.json").write_text(json.dumps(diagnostic, indent=2), encoding="utf-8")
            report["contact_diagnostics"] = "contacts.json"
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["replay_within_tolerance"]:
            raise RuntimeError("Replay exceeded tolerance; inspect report")
    finally:
        env.close()


if __name__ == "__main__":
    main()
