from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Landmark:
    x: float  # normalized 0..1, left->right
    y: float  # normalized 0..1, top->bottom (image convention)
    z: float = 0.0
    visibility: float = 1.0


# MediaPipe Pose landmark indices used by Desk Sentinel
NOSE = 0
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24
NUM_LANDMARKS = 33
