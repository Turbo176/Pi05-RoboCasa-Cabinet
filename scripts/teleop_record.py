"""Keyboard drawer demonstrations with the shared raw recorder (no model)."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
from _windows_runtime import prepare_runtime
_runtime = prepare_runtime()

import cv2
import glfw
import numpy as np
from OpenGL import GL
from scipy.spatial.transform import Rotation
from pi05_cabinet.envs import add_scene_arguments, make_env_from_args
from pi05_cabinet.recording import EpisodeRecorder


class KeyboardWindow:
    def __init__(self, preview=None):
        if not glfw.init():
            raise RuntimeError("GLFW initialization failed")
        # MuJoCo offscreen rendering leaves the global GLFW VISIBLE hint false.
        glfw.default_window_hints()
        glfw.window_hint(glfw.VISIBLE, glfw.TRUE)
        self.window = glfw.create_window(1024, 800, "Pi05 Cabinet | Keyboard Teleop", None, None)
        if not self.window:
            raise RuntimeError("GLFW window creation failed")
        self.events = []
        glfw.set_input_mode(self.window, glfw.STICKY_KEYS, glfw.TRUE)
        self.preview = preview
        glfw.set_key_callback(self.window, self._key)
        glfw.make_context_current(self.window)
        glfw.swap_interval(0)

    def _key(self, window, key, scancode, action, mods):
        if action == glfw.PRESS:
            self.events.append(key)
            print(f"Keyboard input: {glfw.get_key_name(key, scancode) or key}", flush=True)

    def held(self, key):
        return bool(glfw.get_window_attrib(self.window, glfw.FOCUSED) and glfw.get_key(self.window, key) == glfw.PRESS)

    def display(self, overview, obs, lines):
        glfw.set_window_title(self.window, "Pi05 Cabinet | " + lines[0])
        frame = np.full((800, 1024, 3), (19, 25, 33), dtype=np.uint8)
        frame[65:545, :640] = overview
        frame[65:321, 704:960] = obs["robot0_agentview_left_image"][::-1]
        frame[337:593, 704:960] = obs["robot0_eye_in_hand_image"][::-1]
        cv2.putText(frame, "OVERVIEW", (12, 56), cv2.FONT_HERSHEY_SIMPLEX, .55, (210, 220, 235), 1)
        for i, line in enumerate(lines):
            y = 26 if i == 0 else 617+(i-1)*24
            cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, .51, (190, 235, 205), 1, cv2.LINE_AA)
        glfw.make_context_current(self.window)
        width, height = glfw.get_framebuffer_size(self.window)
        GL.glViewport(0, 0, width, height)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glWindowPos2i(0, height)
        GL.glPixelZoom(width/1024, -height/800)
        GL.glDrawPixels(1024, 800, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, frame)
        if self.preview:
            self.preview.parent.mkdir(parents=True, exist_ok=True)
            readback = GL.glReadPixels(0, 0, width, height, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
            pixels = np.frombuffer(readback, dtype=np.uint8).reshape(height, width, 3)[::-1]
            cv2.imwrite(str(self.preview), cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))
            print(f"OpenGL window framebuffer saved: {self.preview}", flush=True)
            self.preview = None
        glfw.swap_buffers(self.window)

    def close(self):
        glfw.destroy_window(self.window)
        # robosuite owns another context; do not call glfw.terminate().


def keyboard_action(env, window, gripper, align):
    controller = env.robots[0].composite_controller.part_controllers["right"]
    controller.update(force=True)
    amount = .24 if window.held(glfw.KEY_LEFT_SHIFT) else .08
    held = window.held
    delta = amount * np.array([int(held(glfw.KEY_D))-int(held(glfw.KEY_A)),
                              int(held(glfw.KEY_W))-int(held(glfw.KEY_S)),
                              int(held(glfw.KEY_R))-int(held(glfw.KEY_F))], dtype=float)
    rotation = .12 * np.array([int(held(glfw.KEY_J))-int(held(glfw.KEY_L)),
                               int(held(glfw.KEY_I))-int(held(glfw.KEY_K)),
                               int(held(glfw.KEY_U))-int(held(glfw.KEY_O))], dtype=float)
    if np.any(rotation):
        align = False
    if align:
        # Operator-selected fixed orientation; no drawer/handle pose is read.
        target = np.array([[0., -1, 0], [0, 0, 1], [-1, 0, 0]])
        rotation = np.clip(Rotation.from_matrix(target @ controller.ref_ori_mat.T).as_rotvec() / .5 * .4, -.4, .4)
    action = np.zeros(env.action_dim)
    action[:3] = controller.origin_ori.T @ delta
    action[3:6] = controller.origin_ori.T @ rotation
    action[6], action[-1] = gripper, -1
    return action, align


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_scene_arguments(parser)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("data/raw/teleop"))
    parser.add_argument("--operator", choices=["human", "agent_ui_check"], default="human")
    parser.add_argument("--max-steps", type=int, default=1200,
                        help="Pause every N control steps; Space extends by N. 0 disables the limit.")
    parser.add_argument("--preview-output", type=Path, help="Save first rendered UI framebuffer for diagnostics")
    args = parser.parse_args()
    if args.max_steps < 0:
        parser.error("--max-steps must be non-negative (0 means unlimited)")
    env = make_env_from_args(args)
    recorder = window = None
    try:
        obs = env.reset()
        window = KeyboardWindow(args.preview_output)
        overview = env.sim.render(width=640, height=480, camera_name="cabinet_overview")[::-1].copy()
        active, gripper, align, seed = False, -1, False, args.seed
        step_limit = args.max_steps
        notice = "READY: Enter starts recording; focus this window to control."
        print(notice, flush=True)
        while not glfw.window_should_close(window.window):
            tick = time.perf_counter()
            glfw.poll_events()
            events, window.events = window.events, []
            if glfw.KEY_ESCAPE in events:
                break
            for key in events:
                if key == glfw.KEY_ENTER and recorder is None:
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    mode = "KEYBOARD_TELEOP" if args.operator == "human" else "AGENT_UI_CHECK"
                    recorder = EpisodeRecorder(args.output / f"{args.task}_s{seed}_{stamp}", env, obs,
                        task=args.task, seed=seed, mode=mode, source=args.operator,
                        extra={"orientation_assist": "operator toggle P: fixed orientation; proprioception only",
                               "step_limit_increment": args.max_steps})
                    step_limit = args.max_steps
                    active = True
                    notice = "RECORDING: F8 saves; F9 discards; Space pauses."
                    print(f"Recording started: {recorder.output}", flush=True)
                elif key == glfw.KEY_SPACE and recorder:
                    if step_limit and recorder.steps >= step_limit:
                        step_limit += args.max_steps
                        active = True
                        notice = f"LIMIT EXTENDED to {step_limit} steps. Space pauses; F8 saves."
                        print(notice, flush=True)
                    else:
                        active = not active
                        notice = "RECORDING: F8 saves; F9 discards; Space pauses." if active else "PAUSED: Space resumes; F8 saves; F9 discards."
                elif key == glfw.KEY_TAB:
                    gripper = -gripper
                elif key == glfw.KEY_P:
                    align = not align
                elif key in (glfw.KEY_F8, glfw.KEY_F9) and recorder:
                    if key == glfw.KEY_F8 and recorder.steps:
                        report = recorder.finish()
                        print(json.dumps({"output":str(recorder.output), **report}, indent=2), flush=True)
                        notice = f"SAVED ({report['steps']} steps, success={report['success_final']}). Enter: next episode."
                    else:
                        recorder.abort("Operator discarded recording")
                        notice = "DISCARDED (partial retained). Enter: next episode."
                    recorder = None
                    active, gripper, align = False, -1, False
                    step_limit = args.max_steps
                    seed += 1
                    env.close()
                    env = make_env_from_args(args, seed=seed)
                    obs = env.reset()
                    overview = env.sim.render(width=640, height=480, camera_name="cabinet_overview")[::-1].copy()
                    print(notice, flush=True)
            focused = bool(glfw.get_window_attrib(window.window, glfw.FOCUSED))
            if recorder and active and focused and (not step_limit or recorder.steps < step_limit):
                action, align = keyboard_action(env, window, gripper, align)
                obs, reward, done, _ = env.step(action)
                overview = recorder.append(action, obs, "keyboard_align" if align else "keyboard", reward, done)
                if step_limit and recorder.steps >= step_limit:
                    active = False
                    notice = f"LIMIT: Space adds {args.max_steps/20:g}s and resumes; F8 saves; F9 discards."
                    print(notice, flush=True)
            opening = float(env.drawer.get_door_state(env=env)["door"])
            if recorder is None:
                state = "READY"
            elif step_limit and recorder.steps >= step_limit:
                state = "LIMIT - SPACE TO EXTEND"
            elif not focused:
                state = "UNFOCUSED - CLICK WINDOW"
            else:
                state = "RECORDING" if active else "PAUSED - SPACE TO RESUME"
            budget = str(step_limit) if step_limit else "unlimited"
            task_line = f"Instruction: {env.get_ep_meta()['lang']}"
            if hasattr(env, "task_metrics"):
                metrics = env.task_metrics()
                task_line += f"   Other drawer unchanged: {metrics['non_target_unchanged']}"
            lines = [f"{args.task} | {args.operator} | seed={seed} | {state} | steps={recorder.steps if recorder else 0} | success={env._check_success()}",
                notice, f"steps={recorder.steps if recorder else 0}/{budget} opening={opening:.3f} gripper={'CLOSE' if gripper>0 else 'OPEN'} align={align}",
                "W/S: world +Y/-Y (in/out)   A/D: -X/+X   R/F: up/down   Shift: faster",
                "J/L: rotate X   I/K: rotate Y   U/O: rotate Z   Tab: open/close gripper",
                "P: fixed handle-grasp orientation assist (robot proprioception only)",
                "Enter: record   Space: pause/resume/extend limit   F8: save   F9: discard   Esc: exit",
                task_line,
                "KEYBOARD TELEOP / NO LEARNED POLICY; failed episodes are kept with success=False."]
            window.display(overview, obs, lines)
            time.sleep(max(0., .05-(time.perf_counter()-tick)))
    finally:
        if recorder:
            recorder.abort("Window closed / Esc / interrupted; not a completed demonstration")
        if window:
            window.close()
        env.close()


if __name__ == "__main__":
    main()
