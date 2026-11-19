"""Privileged-state pose servo baseline; never used by the learned policy."""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation


class DrawerScript:
    """Fixed waypoint plan with closed-loop OSC pose error feedback.

    The handle location comes from simulator ground truth. Only env.step
    drives the robot; the controller does not write simulator state.
    """
    revision = "lower_handle_clearance_v2"

    def __init__(self, env):
        self.env = env
        self.controller = env.robots[0].composite_controller.part_controllers["right"]
        handle_name = f"{env.drawer.name}_door_handle_handle"
        handle = env.sim.data.get_geom_xpos(handle_name).copy()
        grasp = handle + [0, .005, 0]  # pad centre is slightly behind grip_site
        destination = grasp.copy()
        if env.behavior == "open":
            destination[1] -= env.drawer.size[1] * .55
        else:
            destination[1] = env.drawer.pos[1] - env.drawer.size[1]/2 - .030
        above = np.array([grasp[0], min(grasp[1]-.35, -.70), 1.15])
        if getattr(env, "pair_layout", None) == "spaced":
            # Clear the upper drawer before descending in front of the cabinet.
            above[2] = float(env.drawers["top"].pos[2]) + .30
        pregrasp = np.array([grasp[0], min(grasp[1]-.30, -.65), grasp[2]])
        retreat = destination + [0, -.15, .08]
        lower_close = getattr(env, "target_drawer", None) == "bottom" and env.behavior == "close"
        if lower_close:
            # Simultaneous lift / withdrawal can hook a low bar with an open finger.
            # Withdraw horizontally at the handle height instead.
            retreat[2] = destination[2] - .025
        self.stages = [
            ("approach_above", above, -1, 70),
            ("align_height", pregrasp, -1, 60),
            ("reach_handle", grasp, -1, 70),
            ("grasp", grasp, 1, 30),
            ("pull" if env.behavior == "open" else "push", destination, 1, 100),
            ("hold", destination, 1, 20),
            ("release", destination, -1, 25),
            ("retreat", retreat, -1, 40),
        ]
        if getattr(env, "target_drawer", None) == "bottom":
            # The lower handle needs a longer descent and approach. Keep the
            # complete script below the shared 600-control-step evaluation budget.
            durations = {"align_height": 140, "reach_handle": 120}
            self.stages = [(name, target, grip, durations.get(name, steps))
                           for name, target, grip, steps in self.stages]
        if lower_close:
            # Seed 102 contact replay showed the lower open pad still loading
            # the bar at release, with the tool about 25 mm above its waypoint.
            # Unload it vertically before withdrawing; keep collisions active.
            self.stages.insert(-1, ("clear_handle", destination + [0, 0, -.025], -1, 25))
        # Panda's closing axis at grip_site is X; close vertically over the bar.
        self.orientation = np.array([[0., -1, 0], [0, 0, 1], [-1, 0, 0]])

    def actions(self):
        for name, target, gripper, steps in self.stages:
            for _ in range(steps):
                self.controller.update(force=True)
                position_error = target - self.controller.ref_pos
                rotation_error = Rotation.from_matrix(
                    self.orientation @ self.controller.ref_ori_mat.T
                ).as_rotvec()
                action = np.zeros(self.env.action_dim)
                action[:3] = np.clip(self.controller.origin_ori.T @ position_error / .05 * .4, -.35, .35)
                action[3:6] = np.clip(self.controller.origin_ori.T @ rotation_error / .5 * .4, -.5, .5)
                action[6] = gripper
                action[-1] = -1  # arm mode; stationary base and torso
                yield name, action


class FeedbackDrawerScript(DrawerScript):
    """Opt-in demonstration controller with measured stage transitions.

    Contact and fixture truth are for scripted collection only. A phase that
    misses its gate stops the episode; it never silently starts pulling.
    The original fixed controller remains available for frozen collections.
    """
    revision = "pose_contact_feedback_v4"
    max_control_steps = 600
    contact_force_threshold_n = .001

    def __init__(self, env):
        super().__init__(env)
        bottom = getattr(env, "target_drawer", None) == "bottom"
        spawn = env.get_ep_meta()["init_robot_base_pos"]
        self.wrist_flipped = bool(bottom and spawn[0] < env.drawer.pos[0])
        if self.wrist_flipped:
            # The symmetric jaws keep their vertical closing axis and forward
            # approach direction; wrist roll selects a different arm posture.
            self.orientation = self.orientation @ np.diag([-1., -1., 1.])
        limits = dict(approach_above=60, align_height=200, reach_handle=140,
                      grasp=35, pull=120, push=120, hold=10, release=25,
                      clear_handle=70, retreat=40)
        stages = []
        for name, target, gripper, steps in self.stages:
            target = target.copy()
            if bottom and name == "align_height":
                top_handle = env.sim.data.get_geom_xpos(
                    f"{env.drawers['top'].name}_door_handle_handle")
                # Descend outside the upper handle, without the unnecessarily
                # distant lower pregrasp of the fixed-time trajectory.
                target[1] = min(self.stages[2][1][1] - .15, top_handle[1] - .12)
            elif name == "align_height":
                target[1] = self.stages[2][1][1] - .15
            stages.append((name, target, gripper, limits[name]))
        self.stages = stages
        self.execution = dict(controller_revision=self.revision, completed=False,
                              stop_reason=None, steps=0, stages=[],
                              wrist_flipped=self.wrist_flipped)

    def _loaded_pads(self):
        """Loaded target-handle pads at the final sampled physics substep."""
        handle = f"{self.env.drawer.name}_door_handle_handle"
        pads = set()
        for index in range(self.env.sim.data.ncon):
            contact = self.env.sim.data.contact[index]
            names = [self.env.sim.model.geom_id2name(int(geom)) or ""
                     for geom in (contact.geom1, contact.geom2)]
            if handle not in names:
                continue
            force = np.zeros(6)
            mujoco.mj_contactForce(self.env.sim.model._model, self.env.sim.data._data, index, force)
            if np.linalg.norm(force[:3]) <= self.contact_force_threshold_n:
                continue
            for finger in (1, 2):
                if any(f"finger{finger}_pad_collision" in name for name in names):
                    pads.add(finger)
        return pads

    def _gate(self, name, target):
        self.controller.update(force=True)
        error = float(np.linalg.norm(target - self.controller.ref_pos))
        rotation_error = float(np.linalg.norm(Rotation.from_matrix(
            self.orientation @ self.controller.ref_ori_mat.T).as_rotvec()))
        pads = self._loaded_pads()
        if name in ("align_height", "reach_handle"):
            tolerance = .018 if name == "align_height" else .025
            passed = error < tolerance and rotation_error < .1
        elif name == "grasp":
            passed = pads == {1, 2}
        elif name in ("pull", "push"):
            passed = bool(self.env._check_success())
        elif name == "clear_handle":
            gripper_open = np.min(np.abs(self.env.sim.data.qpos[
                self.env.robots[0]._ref_gripper_joint_pos_indexes["right"]])) > .03
            passed = not pads and gripper_open and error < .025 and rotation_error < .1
        else:
            passed = None  # bounded fixed-duration conditioning / settling
        return passed, dict(position_error_m=error, orientation_error_rad=rotation_error,
                            loaded_target_pad_ids=sorted(pads))

    def actions(self):
        for name, target, gripper, maximum in self.stages:
            stable = 0
            for stage_step in range(1, maximum + 1):
                self.controller.update(force=True)
                position_error = target - self.controller.ref_pos
                rotation_error = Rotation.from_matrix(
                    self.orientation @ self.controller.ref_ori_mat.T).as_rotvec()
                action = np.zeros(self.env.action_dim)
                gain = .6 if name in ("align_height", "clear_handle") else .4
                action[:3] = np.clip(self.controller.origin_ori.T @ position_error / .05 * gain, -.35, .35)
                action[3:6] = np.clip(self.controller.origin_ori.T @ rotation_error / .5 * .4, -.5, .5)
                action[6], action[-1] = gripper, -1
                yield name, action
                self.execution["steps"] += 1
                passed, measured = self._gate(name, target)
                stable = stable + 1 if passed else 0
                if (stable >= 5 and stage_step >= 10) or self.execution["steps"] >= self.max_control_steps:
                    break
            gate_passed = passed is None or stable >= 5
            self.execution["stages"].append(dict(name=name, steps=stage_step,
                gated=passed is not None, gate_passed=gate_passed, **measured))
            if self.execution["steps"] >= self.max_control_steps and (name != "retreat" or stage_step < maximum):
                self.execution["stop_reason"] = "control_budget_exhausted"
                return
            if not gate_passed:
                self.execution["stop_reason"] = f"stage_gate_timeout:{name}"
                return
        self.execution["completed"] = True
