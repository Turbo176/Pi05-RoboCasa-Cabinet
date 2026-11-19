"""Shared raw episode recorder for scripted baselines and keyboard teleoperation."""
import hashlib
import json
import platform
import time
from pathlib import Path

import h5py
import imageio.v2 as imageio
import mujoco
import numpy as np
import robocasa
import robosuite
from PIL import Image, ImageDraw


def label(frame, task, seed, stage, opening, success, mode="SCRIPTED_PRIVILEGED_STATE",
          instruction=None, task_metrics=None):
    image = Image.fromarray(frame)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, 51), fill=(15, 19, 25))
    draw.text((12, 7), f"{mode} | {task} | seed={seed} | 1x", fill="white")
    draw.text((12, 28), f"stage={stage} | opening={opening:.3f} | success={success}", fill=(160, 225, 180))
    if instruction:
        draw.rectangle((0, image.height-48, image.width, image.height), fill=(15, 19, 25))
        draw.text((12, image.height-43), instruction, fill="white")
        if task_metrics:
            values = " | ".join(f"{name}={value:.3f}" for name, value in task_metrics["drawer_fractions"].items())
            draw.text((12, image.height-23), f"{values} | other unchanged={task_metrics['non_target_unchanged']}", fill=(160, 225, 180))
    return np.asarray(image)


class EpisodeRecorder:
    """Stream aligned data; incomplete or discarded episodes retain partial files."""
    def __init__(self, output, env, obs, *, task, seed, mode, source, extra=None):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.env, self.task, self.seed, self.mode = env, task, seed, mode
        self.started = time.perf_counter()
        self.closed = False
        self.steps = self.bilateral = 0
        self.fractions, self.successes = [], []
        self.final_frame = None
        self.video_name = "scripted.mp4" if mode == "SCRIPTED_PRIVILEGED_STATE" else "teleop.mp4"
        self.metadata = dict(env.get_ep_meta())
        self.metadata.update(dict(
            schema_version="cabinet_raw_v1", policy_mode=mode, learned_policy=False,
            source=source, task_variant=task, seed=seed, control_hz=20,
            image_convention="opengl-bottom-left-rgb; flip rows for dataset conversion",
            alignment="observations[t], actions[t], observations[t+1]",
            action_semantics="OSC_POSE base-frame normalized delta; gripper +1 close/-1 open; arm mode -1",
            action_split_indexes=dict(env.robots[0]._action_split_indexes),
        ))
        self.metadata.update(extra or {})
        self.file = h5py.File(self.output / "episode.partial.hdf5", "x")
        self.file.attrs["metadata_json"] = json.dumps(self.metadata)
        self.file.attrs["complete"] = False
        self.file.attrs["versions_json"] = json.dumps(dict(
            python=platform.python_version(), mujoco=mujoco.__version__,
            robosuite=robosuite.__version__, robocasa=robocasa.__version__))
        self.file.create_dataset("model_xml", data=env.sim.model.get_xml(), dtype=h5py.string_dtype())
        self.file.create_dataset("initial_sim_state", data=env.sim.get_state().flatten().copy())
        self.file.create_group("observations")
        for key, value in obs.items():
            self._append("observations/" + key, np.asarray(value))
        self._append("sim_qpos", env.sim.data.qpos.copy())
        self._append("sim_qvel", env.sim.data.qvel.copy())
        self._append("sim_time", env.sim.data.time)
        self._append("wall_time", 0.)
        if hasattr(env, "task_metrics"):
            self._append("evaluation/drawer_open_fractions", list(env.drawer_fractions().values()))
        self.writer = imageio.get_writer(self.output / self.video_name, fps=20, codec="libx264", quality=8)

    def _append(self, key, value):
        value = np.asarray(value)
        if key not in self.file:
            if value.dtype.kind in "UO":
                self.file.create_dataset(key, shape=(0,), maxshape=(None,), dtype=h5py.string_dtype())
            else:
                kwargs = dict(compression="gzip", compression_opts=1) if value.ndim else {}
                self.file.create_dataset(key, shape=(0, *value.shape), maxshape=(None, *value.shape),
                                         chunks=(1, *value.shape), dtype=value.dtype, **kwargs)
        ds = self.file[key]
        ds.resize(len(ds) + 1, axis=0)
        ds[-1] = value

    def append(self, action, obs, stage, reward=0., done=False):
        action = np.asarray(action)
        if action.shape != (self.env.action_dim,) or not np.isfinite(action).all():
            raise ValueError("Invalid robot action")
        self._append("actions", action)
        self._append("stage", stage)
        self._append("reward", reward)
        self._append("done", done)
        for key, value in obs.items():
            self._append("observations/" + key, value)
        self._append("sim_qpos", self.env.sim.data.qpos.copy())
        self._append("sim_qvel", self.env.sim.data.qvel.copy())
        self._append("sim_time", self.env.sim.data.time)
        self._append("wall_time", time.perf_counter() - self.started)
        opening = float(self.env.drawer.get_door_state(env=self.env)["door"])
        success = bool(self.env._check_success())
        self.fractions.append(opening)
        self.successes.append(success)
        self._append("drawer_open_fraction", opening)
        self._append("success", success)
        metrics = self.env.task_metrics() if hasattr(self.env, "task_metrics") else None
        if metrics:
            self._append("evaluation/drawer_open_fractions", list(metrics["drawer_fractions"].values()))
            self._append("evaluation/non_target_max_drift", metrics["non_target_max_drift"])
        touched = set()
        for contact in self.env.sim.data.contact:
            names = [self.env.sim.model.geom_id2name(contact.geom1), self.env.sim.model.geom_id2name(contact.geom2)]
            if f"{self.env.drawer.name}_door_handle_handle" in names:
                for name in names:
                    if name and "finger1_pad_collision" in name:
                        touched.add(1)
                    if name and "finger2_pad_collision" in name:
                        touched.add(2)
        self.bilateral += int(touched == {1, 2})
        self.steps += 1
        rgb = self.env.sim.render(width=640, height=480, camera_name="cabinet_overview")[::-1].copy()
        self.final_frame = label(rgb, self.task, self.seed, stage, opening, success, self.mode,
                                 self.metadata["lang"] if metrics else None, metrics)
        self.writer.append_data(self.final_frame)
        if stage == "hold":
            imageio.imwrite(self.output / "held.png", self.final_frame)
        if self.steps % 20 == 0:
            self.file.flush()
        return rgb

    def finish(self, extra=None):
        if self.steps == 0:
            raise ValueError("Cannot save an empty episode")
        elapsed = time.perf_counter() - self.started
        self.file.close()
        self.writer.close()
        self.closed = True
        final = self.output / "episode.hdf5"
        partial = self.output / "episode.partial.hdf5"
        imageio.imwrite(self.output / "final.png", self.final_frame)
        with h5py.File(partial, "r") as file:
            assert all(len(v) == self.steps + 1 for v in file["observations"].values())
            assert len(file["sim_qpos"]) == self.steps + 1
            assert np.isfinite(file["actions"][:]).all()
            assert np.allclose(np.diff(file["sim_time"][:]), .05, atol=1e-6)
            if "evaluation" in file:
                assert len(file["evaluation/drawer_open_fractions"]) == self.steps + 1
                assert len(file["evaluation/non_target_max_drift"]) == self.steps
        with imageio.get_reader(self.output / self.video_name) as reader:
            assert reader.get_data(0).shape == reader.get_data(self.steps-1).shape == (480, 640, 3)
        with h5py.File(partial, "r+") as file:
            file.attrs["complete"] = True
        partial.rename(final)
        report = dict(
            task=self.task, seed=self.seed, mode=self.mode, source=self.metadata["source"],
            learned_policy=False, benchmark="custom Lite; not full RoboCasa benchmark",
            steps=self.steps, sim_seconds=self.steps/20, wall_seconds=elapsed,
            steps_per_second=self.steps/elapsed, language=self.metadata["lang"],
            final_drawer_open_fraction=self.fractions[-1], max_drawer_open_fraction=max(self.fractions),
            success_final=self.successes[-1], success_any=any(self.successes),
            success_stable_last_10=len(self.successes)>=10 and all(self.successes[-10:]),
            bilateral_handle_contact_steps=self.bilateral,
            saved_alignment_and_video_decode_passed=True,
        )
        report.update(extra or {})
        if hasattr(self.env, "task_metrics"):
            report.update(self.env.task_metrics())
            report["scene_parameters"] = self.metadata["scene_parameters"]
        with final.open("rb") as stream:
            report["episode_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        (self.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    def abort(self, reason="discarded"):
        if not self.closed:
            self.file.close()
            self.writer.close()
            self.closed = True
            (self.output / "DISCARDED.txt").write_text(reason, encoding="utf-8")
