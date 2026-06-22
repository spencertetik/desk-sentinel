from pathlib import Path

import pytest

from sentinel.calibration import Baseline, aggregate_baseline, save_baseline, load_baseline
from sentinel.metrics import RawPosture


def _raw(fh, tr, sy, present=True, sx=0.5):
    return RawPosture(fh, tr, sy, present=present, side="left", shoulder_x=sx)


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


def test_aggregate_derives_seat_roi_around_observed_shoulders():
    # User sat with shoulders clustered near x=0.60, y~0.40-0.42.
    samples = [
        _raw(2.0, 3.0, 0.40, sx=0.60),
        _raw(4.0, 5.0, 0.42, sx=0.62),
        _raw(0, 0, 0, present=False, sx=0.95),  # ignored
    ]
    b = aggregate_baseline(samples, margin_x=0.12, margin_y=0.15)
    assert b.seat_roi is not None
    x0, y0, x1, y1 = b.seat_roi
    # zone brackets the observed shoulder x-range with margin
    assert x0 < 0.60 < x1 and x0 < 0.62 < x1
    # and excludes the far-right phantom location (x=0.95)
    assert x1 < 0.95


def test_seat_roi_survives_save_load_roundtrip(tmp_path: Path):
    b = Baseline(forward_head_deg=3.0, trunk_lean_deg=4.0, shoulder_y=0.41,
                 seat_roi=(0.30, 0.20, 0.70, 0.85))
    p = tmp_path / "baseline.json"
    save_baseline(p, b)
    loaded = load_baseline(p)
    assert loaded.seat_roi is not None
    assert tuple(loaded.seat_roi) == (0.30, 0.20, 0.70, 0.85)


def test_load_legacy_baseline_without_seat_roi(tmp_path: Path):
    # An older baseline.json predating the seat zone must still load (roi=None).
    p = tmp_path / "baseline.json"
    p.write_text('{"forward_head_deg": 3.0, "trunk_lean_deg": 4.0, "shoulder_y": 0.41, "ear_y": 0.2}')
    loaded = load_baseline(p)
    assert loaded is not None
    assert loaded.seat_roi is None
