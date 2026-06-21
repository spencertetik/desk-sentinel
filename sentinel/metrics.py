from __future__ import annotations

import math
from dataclasses import dataclass

from sentinel.landmarks import (
    Landmark,
    LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP,
)


@dataclass(frozen=True)
class RawPosture:
    forward_head_deg: float  # angle of shoulder->ear vector from vertical; larger = more forward head
    trunk_lean_deg: float    # angle of hip->shoulder vector from vertical (UNRELIABLE seated: hips occluded)
    shoulder_y: float        # normalized vertical position of the used shoulder (for slump baseline)
    present: bool
    side: str                # 'left' | 'right' | 'none'
    ear_y: float = 0.0       # normalized vertical position of the used ear; head-drop vs neutral is the
                             # reliable seated lean/slouch signal (hips are not visible behind the desk)


def angle_from_vertical(a: Landmark, b: Landmark) -> float:
    """Angle in degrees between the segment a->b and the vertical axis.

    0 = perfectly vertical, 90 = perfectly horizontal. Direction-agnostic.
    """
    dx = abs(b.x - a.x)
    dy = abs(b.y - a.y)
    return math.degrees(math.atan2(dx, dy))


def _side_visibility(pts, ear, shoulder, hip) -> float:
    return (pts[ear].visibility + pts[shoulder].visibility + pts[hip].visibility) / 3.0


def compute_posture(pts: list[Landmark], min_visibility: float) -> RawPosture:
    left_vis = _side_visibility(pts, LEFT_EAR, LEFT_SHOULDER, LEFT_HIP)
    right_vis = _side_visibility(pts, RIGHT_EAR, RIGHT_SHOULDER, RIGHT_HIP)

    if max(left_vis, right_vis) < min_visibility:
        return RawPosture(0.0, 0.0, 0.0, present=False, side="none")

    if left_vis >= right_vis:
        side, ear, shoulder, hip = "left", LEFT_EAR, LEFT_SHOULDER, LEFT_HIP
    else:
        side, ear, shoulder, hip = "right", RIGHT_EAR, RIGHT_SHOULDER, RIGHT_HIP

    forward_head = angle_from_vertical(pts[shoulder], pts[ear])
    trunk_lean = angle_from_vertical(pts[hip], pts[shoulder])
    return RawPosture(
        forward_head_deg=forward_head,
        trunk_lean_deg=trunk_lean,
        shoulder_y=pts[shoulder].y,
        present=True,
        side=side,
        ear_y=pts[ear].y,
    )
