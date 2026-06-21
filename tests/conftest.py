from __future__ import annotations

import pytest

from sentinel.landmarks import (
    Landmark, NUM_LANDMARKS,
    LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP,
)


def make_landmarks(overrides: dict[int, Landmark], default_vis: float = 1.0):
    """Build a full 33-landmark list, with given indices overridden."""
    pts = [Landmark(0.5, 0.5, 0.0, default_vis) for _ in range(NUM_LANDMARKS)]
    for idx, lm in overrides.items():
        pts[idx] = lm
    return pts


@pytest.fixture
def upright_left_profile():
    """Left side faces camera; ear directly above shoulder; shoulder above hip."""
    return make_landmarks({
        LEFT_EAR: Landmark(0.50, 0.20, 0.0, 0.99),
        LEFT_SHOULDER: Landmark(0.50, 0.40, 0.0, 0.99),
        LEFT_HIP: Landmark(0.50, 0.80, 0.0, 0.99),
        # right side mostly occluded in profile
        RIGHT_EAR: Landmark(0.48, 0.20, 0.0, 0.10),
        RIGHT_SHOULDER: Landmark(0.48, 0.40, 0.0, 0.10),
        RIGHT_HIP: Landmark(0.48, 0.80, 0.0, 0.10),
    })
