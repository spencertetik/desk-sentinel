from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sentinel.metrics import RawPosture


@dataclass(frozen=True)
class Baseline:
    forward_head_deg: float
    trunk_lean_deg: float
    shoulder_y: float
    ear_y: float = 0.0  # neutral (upright) ear height; head drop below this signals slouch/lean
    # Seat zone (normalized [x0, y0, x1, y1]) learned from where the user's
    # shoulder sat during calibration. Used to reject pose detections elsewhere
    # in the frame (e.g. an empty chair across the room). None = no gate.
    seat_roi: tuple[float, float, float, float] | None = None


def aggregate_baseline(
    samples: list[RawPosture],
    margin_x: float = 0.12,
    margin_y: float = 0.15,
) -> Baseline:
    present = [s for s in samples if s.present]
    if not present:
        raise ValueError("no present samples to build a baseline from")
    n = len(present)

    xs = [s.shoulder_x for s in present]
    ys = [s.shoulder_y for s in present]
    seat_roi = (
        max(0.0, min(xs) - margin_x),
        max(0.0, min(ys) - margin_y),
        min(1.0, max(xs) + margin_x),
        min(1.0, max(ys) + margin_y),
    )

    return Baseline(
        forward_head_deg=sum(s.forward_head_deg for s in present) / n,
        trunk_lean_deg=sum(s.trunk_lean_deg for s in present) / n,
        shoulder_y=sum(s.shoulder_y for s in present) / n,
        ear_y=sum(s.ear_y for s in present) / n,
        seat_roi=seat_roi,
    )


def save_baseline(path: str | Path, baseline: Baseline) -> None:
    Path(path).write_text(json.dumps(asdict(baseline), indent=2))


def load_baseline(path: str | Path) -> Baseline | None:
    p = Path(path)
    if not p.exists():
        return None
    return Baseline(**json.loads(p.read_text()))
