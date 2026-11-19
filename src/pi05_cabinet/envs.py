"""Small RoboCasa drawer scene built entirely with upstream fixtures.

Single-drawer Lite variants inherit RoboCasa task reset, placement, language
and success. Paired variants extend target binding, reset and non-target
checks. All use upstream fixtures and robosuite textures without sampled
loose objects. They are NOT the full RoboCasa benchmark.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

import robosuite
from robocasa.environments.kitchen.atomic.kitchen_drawer import OpenDrawer, CloseDrawer
from robocasa.environments.kitchen.kitchen import Kitchen
from robocasa.utils.env_utils import create_env

LITE_TASKS = ("OpenDrawerLite", "CloseDrawerLite", "OpenDrawerPairLite", "CloseDrawerPairLite")
PAIR_INSTRUCTIONS = tuple(f"{verb} the {target} drawer."
                          for verb in ("Open", "Close") for target in ("top", "bottom"))


def parse_pair_instruction(instruction):
    """An explicit task grammar, not an NLP model or a learned language policy."""
    if instruction not in PAIR_INSTRUCTIONS:
        raise ValueError(f"Expected one of {PAIR_INSTRUCTIONS}, got {instruction!r}")
    words = instruction.split()
    return words[0].lower(), words[2]


class LocalAssetPaths:
    """Preserve existing local assets through upstream POSIX relocation code.

    Kitchen.edit_model_xml assumes /robocasa/ and /robosuite/ separators,
    and relocates shared textures to RoboCasa's root. Existing local paths
    need no relocation. Keep all upstream camera processing, then restore
    these paths as portable forward-slash absolute paths for MuJoCo.
    """
    def edit_model_xml(self, xml_str):
        root = ET.fromstring(xml_str)
        preserved = {}
        for element in root.findall("./asset/*"):
            file = element.get("file")
            if file and Path(file).is_file():
                token = f"CABINET_LOCAL_ASSET_{len(preserved)}"
                preserved[token] = Path(file).resolve().as_posix()
                element.set("file", token)
        result = super().edit_model_xml(ET.tostring(root, encoding="unicode"))
        root = ET.fromstring(result)
        for element in root.findall("./asset/*"):
            file = element.get("file")
            if file in preserved:
                element.set("file", preserved[file])
        eye = np.array([2.3, -2.1, 1.6])
        target = np.array([1.05, -.2, .8])
        z = eye - target
        z /= np.linalg.norm(z)
        x = np.cross([0, 0, 1], z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        ET.SubElement(root.find("worldbody"), "camera", name="cabinet_overview",
                      pos=" ".join(map(str, eye)),
                      xyaxes=" ".join(map(str, np.r_[x, y])), fovy="48")
        return ET.tostring(root, encoding="unicode")


class OpenDrawerLite(LocalAssetPaths, OpenDrawer):
    def _get_obj_cfgs(self):
        return []


class CloseDrawerLite(LocalAssetPaths, CloseDrawer):
    def _get_obj_cfgs(self):
        return []


class DrawerPairTask:
    """Two upstream drawers with target-independent initialization.

    Commands are validated and bound to fixture references by the environment.
    DrawerScript still uses privileged state; no language understanding claim
    is made until a trained RGB/state/prompt policy is evaluated here.
    """
    non_target_tolerance = .05  # fraction of depth * .55; about 15 mm

    def __init__(self, *args, instruction, scene_offset=(0., 0.), pair_layout="compact", **kwargs):
        self.instruction = instruction
        behavior, self.target_drawer = parse_pair_instruction(instruction)
        expected = "open" if isinstance(self, OpenDrawer) else "close"
        if behavior != expected:
            raise ValueError("Instruction verb does not match the selected environment")
        self.scene_offset = list(map(float, scene_offset))
        self.pair_layout = pair_layout
        self._initial_drawer_fractions = None
        self._non_target_max_drift = 0.
        super().__init__(*args, **kwargs)

    def _get_obj_cfgs(self):
        return []

    def _setup_kitchen_references(self):
        Kitchen._setup_kitchen_references(self)
        self.drawers = {name: self.get_fixture(f"drawer_{name}") for name in ("top", "bottom")}
        self.drawer = self.register_fixture_ref("drawer", dict(id=self.drawers[self.target_drawer]))
        self.init_robot_base_ref = self.drawers["top"]
        if not self._place_robot():
            raise RuntimeError("No valid robot placement for the paired drawer layout")

    def _place_robot(self):
        target = self.drawer
        self.drawer = self.drawers["top"]
        try:
            return super()._place_robot()
        finally:
            self.drawer = target

    def _setup_scene(self):
        # Fixed iteration order and same states for both targets: changing the
        # target prompt must not change RNG consumption or physical reset.
        for drawer in self.drawers.values():
            if self.behavior == "open":
                drawer.close_door(env=self)
            else:
                drawer.open_door(env=self)  # upstream partial-open reset
        self._initial_drawer_fractions = None
        self._non_target_max_drift = 0.
        Kitchen._setup_scene(self)

    def _reset_internal(self):
        super()._reset_internal()
        self._initial_drawer_fractions = self.drawer_fractions()
        self._non_target_max_drift = 0.

    def drawer_fractions(self):
        return {name: float(drawer.get_door_state(env=self)["door"])
                for name, drawer in self.drawers.items()}

    def _post_action(self, action):
        result = super()._post_action(action)
        self._update_non_target_drift()
        return result

    def _update_non_target_drift(self):
        if self._initial_drawer_fractions is not None:
            fractions = self.drawer_fractions()
            drift = max(abs(fractions[name] - initial)
                        for name, initial in self._initial_drawer_fractions.items()
                        if name != self.target_drawer)
            self._non_target_max_drift = max(self._non_target_max_drift, drift)

    def task_metrics(self):
        self._update_non_target_drift()
        fractions = self.drawer_fractions()
        return dict(target_drawer=self.target_drawer, drawer_fractions=fractions,
                    initial_drawer_fractions=self._initial_drawer_fractions,
                    target_success=bool(super()._check_success()),
                    non_target_max_drift=self._non_target_max_drift,
                    non_target_unchanged=self._non_target_max_drift <= self.non_target_tolerance,
                    non_target_tolerance=self.non_target_tolerance)

    def _check_success(self):
        metrics = self.task_metrics()
        return metrics["target_success"] and metrics["non_target_unchanged"]

    def get_ep_meta(self):
        meta = super().get_ep_meta()
        meta.update(lang=self.instruction, target_drawer=self.target_drawer,
                    scene_variant="stacked_pair_v1", scene_offset=self.scene_offset, pair_layout=self.pair_layout,
                    scene_parameters=dict(instruction=self.instruction, scene_offset=self.scene_offset,
                                          pair_layout=self.pair_layout),
                    drawer_names=list(self.drawers),
                    initial_drawer_fractions=self._initial_drawer_fractions,
                    non_target_tolerance=self.non_target_tolerance)
        return meta


class OpenDrawerPairLite(DrawerPairTask, LocalAssetPaths, OpenDrawer):
    pass


class CloseDrawerPairLite(DrawerPairTask, LocalAssetPaths, CloseDrawer):
    pass


def make_lite_env(task="OpenDrawerLite", seed=0, width=256, height=256,
                  instruction=None, scene_offset=(0., 0.), pair_layout="compact"):
    if task not in LITE_TASKS:
        raise ValueError(f"Unsupported Lite task: {task}")
    paired = task in ("OpenDrawerPairLite", "CloseDrawerPairLite")
    if pair_layout not in ("compact", "spaced"):
        raise ValueError("pair_layout must be compact or spaced")
    offset = np.asarray(scene_offset, dtype=float)
    if offset.shape != (2,) or not np.isfinite(offset).all() or np.max(np.abs(offset)) > .15:
        raise ValueError("scene_offset must contain two finite offsets within +/-0.15m")
    if paired:
        verb = "Open" if task.startswith("Open") else "Close"
        instruction = instruction or f"{verb} the top drawer."
        behavior, _ = parse_pair_instruction(instruction)
        if behavior != verb.lower():
            raise ValueError("Instruction verb does not match the selected environment")
    elif instruction is not None or np.any(offset) or pair_layout != "compact":
        raise ValueError("Explicit instruction/scene offset requires a paired drawer task")
    texture_root = Path(robosuite.__file__).parent / "models" / "assets" / "textures"
    wood = (texture_root / "light-wood.png").as_posix()
    metal = (texture_root / "steel-brushed.png").as_posix()
    floor = (texture_root / "light-gray-floor-tile.png").as_posix()
    layout = {
        "room": {"fixtures": [
            dict(name="floor", type="floor", pos=[1, -.6, -.025],
                 size=[2, 2, .025], texture=floor),
        ]},
        "cabinet": {"fixtures": [
            dict(name="drawer", type="drawer", pos=[1, 0, .85],
                 size=[.6, .55, .20], texture=wood, panel_type="slab",
                 handle_type="bar", handle_config=dict(texture=metal)),
            dict(name="plinth", type="box", pos=[1, 0, .375],
                 size=[.6, .55, .75], texture=wood),
            dict(name="worktop", type="box", pos=[1, 0, .975],
                 size=[.65, .6, .05], texture=wood),
        ]},
    }
    extra = {}
    if paired:
        fixtures = layout["cabinet"]["fixtures"]
        fixtures[0]["name"] = "drawer_top"
        fixtures[1]["pos"][2], fixtures[1]["size"][2] = .25, .50
        fixtures.append(dict(fixtures[0], name="drawer_bottom", pos=[1, 0, .60]))
        fixtures.append(dict(name="separator", type="box", pos=[1, 0, .725],
                             size=[.6, .55, .05], texture=wood))
        if pair_layout == "spaced":
            for fixture in fixtures:
                if fixture["name"] == "drawer_top":
                    fixture["pos"][2] = 1.10
                elif fixture["name"] == "drawer_bottom":
                    fixture["pos"][2] = .72
                elif fixture["name"] == "plinth":
                    fixture["pos"][2], fixture["size"][2] = .31, .62
                elif fixture["name"] == "separator":
                    fixture["pos"][2], fixture["size"][2] = .91, .18
                elif fixture["name"] == "worktop":
                    fixture["pos"][2] = 1.225
        for fixture in fixtures:
            fixture["pos"][0] += float(offset[0])
            fixture["pos"][1] += float(offset[1])
        extra = dict(instruction=instruction, scene_offset=offset.tolist(), pair_layout=pair_layout)
    return create_env(
        task, robots="PandaOmron", seed=seed,
        layout_and_style_ids=[(layout, {})],
        camera_names=["robot0_agentview_left", "robot0_eye_in_hand"],
        camera_widths=width, camera_heights=height,
        renderer="mujoco", control_freq=20, horizon=600,
        randomize_cameras=False, generative_textures=False,
        **extra,
    )


def add_scene_arguments(parser):
    parser.add_argument("--task", choices=LITE_TASKS, default="OpenDrawerLite")
    parser.add_argument("--instruction", choices=PAIR_INSTRUCTIONS,
                        help="Paired drawer task: explicit target command; default top drawer")
    parser.add_argument("--scene-offset", type=float, nargs=2, default=(0., 0.), metavar=("DX", "DY"),
                        help="Paired cabinet translation in metres; stored for exact replay")
    parser.add_argument("--pair-layout", choices=("compact", "spaced"), default="compact",
                        help="Paired drawer geometry; spaced provides more arm clearance")


def make_env_from_args(args, seed=None):
    return make_lite_env(args.task, args.seed if seed is None else seed,
                         instruction=args.instruction, scene_offset=args.scene_offset, pair_layout=args.pair_layout)
