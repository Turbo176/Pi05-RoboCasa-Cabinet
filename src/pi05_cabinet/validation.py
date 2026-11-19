"""Image reset comparison with an explicit, narrowly bounded RGB noise profile.

Physics state, XML and robot placement must still be compared exactly by the
caller. This helper neither scores task success nor changes recorded images.
"""
import numpy as np


def compare_policy_rgb(first, second, profile="exact"):
    first, second = np.asarray(first), np.asarray(second)
    if first.shape != second.shape or first.shape != (256, 256, 3):
        raise ValueError("Expected two equally sized 256x256 RGB images")
    if first.dtype != np.uint8 or second.dtype != np.uint8:
        raise ValueError("Expected raw uint8 RGB images")
    if profile not in ("exact", "lsb_v1"):
        raise ValueError("Unknown RGB comparison profile")
    error = np.abs(first.astype(np.int16) - second.astype(np.int16))
    different_pixels = int(np.any(error != 0, axis=2).sum())
    maximum = int(error.max())
    # Named profile, rather than a user-adjustable threshold that can be
    # increased until a changed scene passes. 16 / 65536 pixels = 0.0244%.
    allowed_error, allowed_pixels = (0, 0) if profile == "exact" else (1, 16)
    return dict(profile=profile, bitwise_identical=different_pixels == 0,
        max_channel_error_uint8=maximum, differing_pixels=different_pixels,
        differing_channels=int((error != 0).sum()),
        allowed_channel_error_uint8=allowed_error, allowed_differing_pixels=allowed_pixels,
        passed=maximum <= allowed_error and different_pixels <= allowed_pixels)
