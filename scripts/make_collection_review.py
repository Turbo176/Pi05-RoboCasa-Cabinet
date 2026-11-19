"""Render recorded policy views for visual review; never run a policy or simulator."""
import argparse
from contextlib import ExitStack
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import h5py
import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pi05_cabinet.adapters import image_keys

CASES = ("open_top", "open_bottom", "close_top", "close_bottom")
ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


@lru_cache(maxsize=16)
def font(size):
    for name in ("C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def panel(file, meta, frame):
    n = len(file["actions"])
    i = min(frame, n - 1)
    image = Image.new("RGB", (576, 416), "#151e2d")
    draw = ImageDraw.Draw(image)
    draw.text((12, 8), meta["lang"], font=font(22), fill="#f1f5f9")
    mapping = image_keys(file["observations"])
    # Post-action observation, matching success[i] and measured fractions[i+1].
    # Flip only the OpenGL row convention, as in the dataset adapter.
    for key, x, size in (("observation.images.front", 12, 320),
                         ("observation.images.wrist", 348, 192)):
        rgb = file["observations"][mapping[key]][i + 1][::-1].copy()
        view = Image.fromarray(rgb).resize((size, size), Image.Resampling.NEAREST)
        image.paste(view, (x, 56))
    draw.text((12, 35), "CABINET FRONT", font=font(12), fill="#94a3b8")
    draw.text((348, 35), "WRIST", font=font(12), fill="#94a3b8")
    top, bottom = file["evaluation/drawer_open_fractions"][i + 1]
    drift = float(file["evaluation/non_target_max_drift"][i])
    stage = file["stage"].asstr()[i]
    success = bool(file["success"][i])
    for j, text in enumerate((f"Top opening: {top:.3f}", f"Bottom opening: {bottom:.3f}",
                              f"Other drift: {drift:.4f}", f"Stage: {stage}")):
        draw.text((348, 266 + 23 * j), text, font=font(15), fill="#cbd5e1")
    draw.text((12, 389), f"{(i+1)/20:.2f}s | step {i+1}/{n}" +
              (" | FINAL FRAME HELD" if frame >= n else ""), font=font(14), fill="#94a3b8")
    draw.text((348, 366), f"Task success: {success}", font=font(16),
              fill="#86efac" if success else "#fcd34d")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", type=Path, required=True,
                        help="Recorded four-command condition directory")
    parser.add_argument("--output", type=Path, required=True, help="New review directory")
    parser.add_argument("--gif", action="store_true", help="Also save a 5 FPS preview at 1x speed")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    paths = [args.condition / case / "episode.hdf5" for case in CASES]
    with ExitStack() as stack:
        files = [stack.enter_context(h5py.File(path, "r")) for path in paths]
        metadata = [json.loads(file.attrs["metadata_json"]) for file in files]
        for file, meta in zip(files, metadata):
            if not file.attrs.get("complete") or meta["policy_mode"] != "SCRIPTED_PRIVILEGED_STATE":
                raise ValueError("Expected completed, explicitly scripted raw recordings")
            if meta["control_hz"] != 20 or meta["scene_parameters"].get("front_camera") != "cabinet_front":
                raise ValueError("Review requires cabinet_front + wrist at 20 Hz")
        if len({(meta["seed"], tuple(meta["scene_offset"]), meta["pair_layout"])
                for meta in metadata}) != 1:
            raise ValueError("One initialization condition is required")
        for case, meta in zip(CASES, metadata):
            behavior, target = case.split("_")
            if meta["lang"] != f"{behavior.capitalize()} the {target} drawer.":
                raise ValueError("Unexpected command order")
        args.output.mkdir(parents=True, exist_ok=False)
        counts = [len(file["actions"]) for file in files]
        if min(counts) < 10:
            raise ValueError("Review requires at least ten recorded actions per episode")
        frames = max(counts)
        video = args.output / "four_commands.mp4"
        previews = []
        with imageio.get_writer(video, fps=20, codec="libx264", quality=8,
                                macro_block_size=16) as writer:
            for i in range(frames):
                canvas = Image.new("RGB", (1152, 896), "#0b1220")
                draw = ImageDraw.Draw(canvas)
                draw.text((12, 3), "PandaOmron | Four drawer commands", font=font(25), fill="#f8fafc")
                draw.text((12, 37), f"SCRIPTED_PRIVILEGED_STATE | seed {metadata[0]['seed']} | "
                          "20 Hz, 1x speed | independent episodes | no model inference",
                          font=font(15), fill="#93c5fd")
                for j, (file, meta) in enumerate(zip(files, metadata)):
                    canvas.paste(panel(file, meta, i), (576 * (j % 2), 64 + 416 * (j // 2)))
                writer.append_data(np.asarray(canvas))
                if args.gif and i % 4 == 0:
                    preview = canvas.resize((640, 498), Image.Resampling.LANCZOS)
                    previews.append(preview.quantize(colors=96))
        canvas.save(args.output / "preview.png")
        sheet = Image.new("RGB", (1728, 1664), "#0b1220")
        source_rows = []
        for j, (case, path, file, meta, n) in enumerate(zip(CASES, paths, files, metadata, counts)):
            stages = file["stage"].asstr()[:]
            grasp = np.flatnonzero(stages == "grasp")
            indices = [0, int(grasp[-1]) if len(grasp) else n // 2, n - 1]
            for col, i in enumerate(indices):
                sheet.paste(panel(file, meta, i), (576 * col, 416 * j))
            source_rows.append(dict(case=case, path=path.resolve().relative_to(ROOT).as_posix(),
                sha256=digest(path), frames=n, sheet_post_action_indices=indices,
                stable_success=bool(file["success"][-10:].all()),
                controller_completed=meta.get("controller_execution", {}).get("completed")))
        sheet.save(args.output / "keyframes.png")
        if args.gif:
            durations = [200] * (len(previews) - 1) + [(frames - 4*(len(previews)-1)) * 50]
            previews[0].save(args.output / "four_commands.gif", save_all=True,
                append_images=previews[1:], duration=durations, loop=0, optimize=False)
        with imageio.get_reader(video) as reader:
            decoded = sum(1 for _ in reader)
            assert reader.get_meta_data()["fps"] == 20
        assert decoded == frames
        report = dict(schema="cabinet_collection_review_v1", source="SCRIPTED_PRIVILEGED_STATE",
            learned_policy=False, script_sha256=digest(__file__), seed=metadata[0]["seed"],
            sources=source_rows, fps=20, frames=frames, duration_seconds=frames/20,
            frame_alignment="post-action RGB[i+1], success[i], drawer fractions[i+1]",
            display="4 independent episodes; shorter clips hold final frame; nearest-neighbor RGB enlargement",
            observations="Recorded cabinet_front and wrist policy RGB; overlays added only in review artifacts",
            human_visual_acceptance="pending; automatically generated review packet is not a human review",
            video_sha256=digest(video), decode_all_frames_passed=True)
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(dict(output=str(args.output), frames=frames, duration_seconds=frames/20,
                              stable_successes=sum(row["stable_success"] for row in source_rows)), indent=2))


if __name__ == "__main__":
    main()
