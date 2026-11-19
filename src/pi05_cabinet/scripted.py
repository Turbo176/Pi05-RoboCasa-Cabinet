"""Privileged-state pose servo baseline; never used by the learned policy."""
import numpy as np
from scipy.spatial.transform import Rotation


class DrawerScript:
    """Fixed waypoint plan with closed-loop OSC pose error feedback.

    The handle location comes from simulator ground truth. Only env.step
    drives the robot; the controller does not write simulator state.
    """
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
        if getattr(env, "target_drawer", None) == "bottom" and env.behavior == "close":
            # Simultaneous lift / withdrawal can hook a low bar with an open finger.
            # Withdraw horizontally at the handle height instead.
            retreat[2] = destination[2]
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
