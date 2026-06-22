from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sentinel.calibration import Baseline
from sentinel.config import Thresholds
from sentinel.metrics import RawPosture


class Posture(str, Enum):
    GOOD = "good"
    FORWARD_HEAD = "forward_head"
    SLOUCHING = "slouching"
    AWAY = "away"


@dataclass(frozen=True)
class Status:
    posture: Posture
    forward_head_deg: float
    trunk_lean_deg: float
    shoulder_drop: float
    head_drop: float = 0.0  # how far the head dropped below the calibrated neutral (normalized)
    active: bool = False     # set by the app loop; True only when present + actively working


def classify(raw: RawPosture, baseline: Baseline | None, thr: Thresholds) -> Status:
    if not raw.present:
        return Status(Posture.AWAY, raw.forward_head_deg, raw.trunk_lean_deg, 0.0, 0.0)

    if baseline is not None:
        fh_limit = baseline.forward_head_deg + thr.forward_head_margin_deg
        shoulder_drop = raw.shoulder_y - baseline.shoulder_y
        # Head drop below neutral is the reliable lean/slouch signal for a seated
        # desk view (hips are occluded, so the hip-based trunk angle is unusable).
        head_drop = raw.ear_y - baseline.ear_y
    else:
        # Without calibration the head-drop signal has no neutral to compare to,
        # so only the absolute forward-head angle can flag anything.
        fh_limit = thr.abs_forward_head_deg
        shoulder_drop = 0.0
        head_drop = 0.0

    if head_drop > thr.head_drop_margin:
        posture = Posture.SLOUCHING
    elif raw.forward_head_deg > fh_limit and head_drop >= -thr.head_drop_margin:
        # The shoulder->ear angle is a 2D projection: turning to face a side
        # screen (e.g. a laptop) tilts that line sideways and spikes the angle
        # without any real slouch. A genuine forward-head lean never *raises* the
        # head above neutral, so if head_drop shows the head clearly higher than
        # the calibrated neutral, treat the big angle as a turn, not bad posture.
        posture = Posture.FORWARD_HEAD
    else:
        posture = Posture.GOOD

    return Status(posture, raw.forward_head_deg, raw.trunk_lean_deg, shoulder_drop, head_drop)
