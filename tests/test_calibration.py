from pathlib import Path

import pytest

from sentinel.calibration import Baseline, aggregate_baseline, save_baseline, load_baseline
from sentinel.metrics import RawPosture


def _raw(fh, tr, sy, present=True):
    return RawPosture(fh, tr, sy, present=present, side="left")


def test_aggregate_averages_present_samples():
    samples = [_raw(2.0, 3.0, 0.40), _raw(4.0, 5.0, 0.42), _raw(0, 0, 0, present=False)]
    b = aggregate_baseline(samples)
    assert abs(b.forward_head_deg - 3.0) < 1e-6
    assert abs(b.trunk_lean_deg - 4.0) < 1e-6
    assert abs(b.shoulder_y - 0.41) < 1e-6


def test_aggregate_raises_when_no_present_samples():
    with pytest.raises(ValueError):
        aggregate_baseline([_raw(0, 0, 0, present=False)])


def test_save_and_load_roundtrip(tmp_path: Path):
    b = Baseline(forward_head_deg=3.0, trunk_lean_deg=4.0, shoulder_y=0.41)
    p = tmp_path / "baseline.json"
    save_baseline(p, b)
    loaded = load_baseline(p)
    assert loaded == b


def test_load_missing_returns_none(tmp_path: Path):
    assert load_baseline(tmp_path / "nope.json") is None
