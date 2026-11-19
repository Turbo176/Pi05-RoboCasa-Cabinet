"""Verify native MuJoCo physics, offscreen RGB, MP4 and optional viewer.

This is a graphics smoke check, NOT a robot task or a learned policy.
"""
import argparse
import json
import platform
import time
from pathlib import Path

from _windows_runtime import prepare_runtime

_runtime = prepare_runtime()

import imageio.v2 as imageio
import mujoco
import numpy as np

XML = """
<mujoco model="native_graphics_smoke">
  <option timestep="0.002"/>
  <visual><global offwidth="640" offheight="480"/></visual>
  <worldbody>
    <light pos="0 -1 3"/>
    <geom type="plane" size="2 2 .1" rgba=".18 .22 .28 1"/>
    <body pos="0 0 .32">
      <geom type="box" size=".32 .26 .03" rgba=".55 .35 .17 1"/>
      <body name="slider" pos="0 0 .08">
        <joint name="slide" type="slide" axis="0 -1 0" range="0 .35" damping="8"/>
        <geom type="box" size=".29 .23 .05" mass="1" rgba=".80 .58 .31 1"/>
        <geom type="capsule" fromto="-.10 -.27 0 .10 -.27 0" size=".012" rgba=".7 .7 .7 1"/>
      </body>
    </body>
  </worldbody>
  <actuator><position joint="slide" kp="100" ctrlrange="0 .35"/></actuator>
</mujoco>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/native_smoke"))
    parser.add_argument("--viewer-seconds", type=float, default=0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    model = mujoco.MjModel.from_xml_string(XML)
    data = mujoco.MjData(model)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = [0, -.08, .25]
    camera.distance, camera.azimuth, camera.elevation = 1.65, 125, -25
    started = time.perf_counter()
    frames = 0
    renderer = mujoco.Renderer(model, height=480, width=640)
    try:
        from OpenGL import GL
        gl_info = {name: GL.glGetString(key).decode() for name, key in (
            ("vendor", GL.GL_VENDOR), ("renderer", GL.GL_RENDERER),
            ("version", GL.GL_VERSION))}
        with imageio.get_writer(args.output / "native_smoke.mp4", fps=25,
                                codec="libx264", quality=7) as writer:
            for step in range(2000):
                data.ctrl[0] = .16 * (1 - np.cos(2*np.pi*step/2000))
                mujoco.mj_step(model, data)
                if step % 20 == 0:
                    renderer.update_scene(data, camera=camera)
                    rgb = renderer.render().copy()
                    assert rgb.shape == (480, 640, 3) and rgb.std() > 5
                    if frames == 30:
                        imageio.imwrite(args.output / "native_smoke.png", rgb)
                    writer.append_data(rgb)
                    frames += 1
    finally:
        renderer.close()
    elapsed = time.perf_counter() - started
    viewer_verified = False
    if args.viewer_seconds > 0:
        from mujoco import viewer as mjviewer
        with mjviewer.launch_passive(model, data) as viewer:
            viewer.cam.lookat[:] = camera.lookat
            viewer.cam.distance = camera.distance
            viewer.cam.azimuth = camera.azimuth
            viewer.cam.elevation = camera.elevation
            until = time.perf_counter() + args.viewer_seconds
            while viewer.is_running() and time.perf_counter() < until:
                data.ctrl[0] = .16 * (1 - np.cos(data.time*2))
                mujoco.mj_step(model, data)
                viewer.sync()
                viewer_verified = True
                time.sleep(.002)
    reader = imageio.get_reader(args.output / "native_smoke.mp4")
    metadata = reader.get_meta_data()
    first = reader.get_data(0)
    last = reader.get_data(frames-1)
    reader.close()
    assert first.shape == last.shape == (480, 640, 3)
    report = {
        "purpose": "native graphics smoke; no robot or learned policy",
        "python": platform.python_version(), "platform": platform.platform(),
        "mujoco": mujoco.__version__, "numpy": np.__version__,
        "opengl": gl_info, "frames": frames, "fps": metadata["fps"],
        "duration_seconds": metadata["duration"],
        "render_and_encode_wall_seconds": elapsed,
        "render_and_encode_fps": frames/elapsed,
        "viewer_launch_and_sync_passed": viewer_verified,
        "video_decode_passed": True,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
