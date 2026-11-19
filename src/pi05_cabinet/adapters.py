"""Versioned observation/action contract shared by datasets and future inference.

No task ground truth is included in the policy observation. The action is the
normalized OSC command, not an absolute pose and not a joint position target.
"""
import numpy as np

SCHEMA_VERSION = "pandaomron_arm_osc_v1"
IMAGE_KEYS = {
    "observation.images.front": "robot0_agentview_left_image",
    "observation.images.wrist": "robot0_eye_in_hand_image",
}
STATE_NAMES = [f"panda_joint_{i}_rad" for i in range(1, 8)] + ["finger_1_m", "finger_2_m"]
ACTION_NAMES = ["base_dx_norm", "base_dy_norm", "base_dz_norm", "base_rx_norm",
                "base_ry_norm", "base_rz_norm", "gripper_close_norm"]


def image_keys(raw_keys):
    """Resolve one explicit front view; retain legacy recording compatibility."""
    candidates = [key for key in ("robot0_agentview_left_image", "cabinet_front_image") if key in raw_keys]
    if len(candidates) != 1 or "robot0_eye_in_hand_image" not in raw_keys:
        raise ValueError("Expected exactly one supported front camera plus the wrist camera")
    return {**IMAGE_KEYS, "observation.images.front": candidates[0]}


def policy_observation(raw):
    joint = np.asarray(raw["robot0_joint_pos"], dtype=np.float32)
    gripper = np.asarray(raw["robot0_gripper_qpos"], dtype=np.float32)
    if joint.shape != (7,) or gripper.shape != (2,):
        raise ValueError("Expected seven Panda joints and two finger positions")
    state = np.concatenate([joint, gripper])
    if not np.isfinite(state).all():
        raise ValueError("Non-finite proprioception")
    result = {"observation.state": state}
    for target, source in image_keys(raw).items():
        image = np.asarray(raw[source])
        if image.shape != (256, 256, 3) or image.dtype != np.uint8:
            raise ValueError(f"Unexpected RGB shape/type for {source}")
        result[target] = image[::-1].copy()  # OpenGL bottom-left -> top-left RGB
    return result


def policy_action(raw_action):
    action = np.asarray(raw_action)
    if action.shape != (12,) or not np.isfinite(action).all():
        raise ValueError("Expected finite 12D PandaOmron action")
    if not np.allclose(action[7:11], 0) or not np.isclose(action[11], -1):
        raise ValueError("7D adapter requires stationary base/torso and arm mode -1")
    if np.max(np.abs(action[:7])) > 1.00001:
        raise ValueError("OSC action outside normalized [-1,1]")
    return action[:7].astype(np.float32)


def robot_action(action):
    action = np.asarray(action, dtype=np.float64)
    if action.shape != (7,) or not np.isfinite(action).all():
        raise ValueError("Expected one finite 7D policy action")
    result = np.zeros(12)
    result[:7] = np.clip(action, -1, 1)
    result[-1] = -1
    return result
