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


def aggregate_baseline(samples: list[RawPosture]) -> Baseline:
    present = [s for s in samples if s.present]
    if not present:
        raise ValueError("no present samples to build a baseline from")
    n = len(present)
    return Baseline(
        forward_head_deg=sum(s.forward_head_deg for s in present) / n,
        trunk_lean_deg=sum(s.trunk_lean_deg for s in present) / n,
        shoulder_y=sum(s.shoulder_y for s in present) / n,
        ear_y=sum(s.ear_y for s in present) / n,
    )


def save_baseline(path: str | Path, baseline: Baseline) -> None:
    Path(path).write_text(json.dumps(asdict(baseline), indent=2))


def load_baseline(path: str | Path) -> Baseline | None:
    p = Path(path)
    if not p.exists():
        return None
    return Baseline(**json.loads(p.read_text()))
