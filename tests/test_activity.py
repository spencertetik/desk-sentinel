"""Tests for sentinel/activity.py — pure functions + ActivityDetector."""
from __future__ import annotations

import numpy as np
import pytest

from sentinel.activity import ActivityDetector, roi_motion


# ---------------------------------------------------------------------------
# roi_motion — pure function tests
# ---------------------------------------------------------------------------

def _gray(h: int, w: int, val: int) -> np.ndarray:
    return np.full((h, w), val, dtype=np.uint8)


def test_roi_motion_identical_frames_returns_zero():
    """Identical frames → zero mean absolute diff."""
    frame = _gray(100, 100, 128)
    assert roi_motion(frame, frame, [0.0, 0.0, 1.0, 1.0]) == 0.0


def test_roi_motion_none_prev_returns_zero():
    """None prev_gray (first tick) → 0."""
    cur = _gray(100, 100, 200)
    assert roi_motion(None, cur, [0.0, 0.0, 1.0, 1.0]) == 0.0


def test_roi_motion_known_delta():
    """Known per-pixel delta → expected mean."""
    # 100×100 frame: prev=0, cur=50 everywhere → mean abs diff = 50.0
    prev = _gray(100, 100, 0)
    cur  = _gray(100, 100, 50)
    result = roi_motion(prev, cur, [0.0, 0.0, 1.0, 1.0])
    assert abs(result - 50.0) < 1e-6


def test_roi_motion_partial_roi():
    """Only the ROI region is compared; outside is ignored."""
    # left half (x < 0.5): prev=0, cur=100  →  diff=100
    # right half: prev=200, cur=200 → diff=0
    # ROI covers left half only → mean=100
    h, w = 10, 10
    prev = np.zeros((h, w), dtype=np.uint8)
    prev[:, w // 2:] = 200
    cur = np.zeros((h, w), dtype=np.uint8)
    cur[:, :w // 2] = 100
    cur[:, w // 2:] = 200

    result = roi_motion(prev, cur, [0.0, 0.0, 0.5, 1.0])
    assert abs(result - 100.0) < 1e-6


def test_roi_motion_clamping_exceeds_bounds():
    """ROI coords > 1.0 are clamped to frame size; result is still valid."""
    prev = _gray(50, 50, 10)
    cur  = _gray(50, 50, 20)
    # x1=1.5 is out of bounds — should clamp to 1.0
    result = roi_motion(prev, cur, [0.0, 0.0, 1.5, 1.5])
    assert abs(result - 10.0) < 1e-6


def test_roi_motion_empty_roi_returns_zero():
    """x1<=x0 or y1<=y0 → empty crop → 0."""
    prev = _gray(50, 50, 10)
    cur  = _gray(50, 50, 20)
    assert roi_motion(prev, cur, [0.5, 0.0, 0.5, 1.0]) == 0.0  # x0==x1
    assert roi_motion(prev, cur, [0.5, 0.5, 0.3, 0.8]) == 0.0  # x1 < x0 (inverted)


def test_roi_motion_small_roi():
    """A tiny 1-pixel ROI at a specific location with known diff."""
    h, w = 10, 10
    prev = np.zeros((h, w), dtype=np.uint8)
    cur  = np.zeros((h, w), dtype=np.uint8)
    # Pixel (5,5) = (row=5, col=5)
    prev[5, 5] = 0
    cur[5, 5]  = 77
    # ROI: x0=0.5, y0=0.5, x1=0.6, y1=0.6 → pixel (5,5) in a 10×10 frame
    result = roi_motion(prev, cur, [0.5, 0.5, 0.6, 0.6])
    assert abs(result - 77.0) < 1e-6


# ---------------------------------------------------------------------------
# ActivityDetector — hysteresis + grace timer tests
# ---------------------------------------------------------------------------

def _make_detector(enter=5.0, exit=2.0, grace=3.0, alpha=1.0):
    """alpha=1.0: no smoothing so motion score == EMA; deterministic tests."""
    return ActivityDetector(enter=enter, exit=exit, idle_grace_s=grace, ema_alpha=alpha)


def test_detector_starts_idle():
    d = _make_detector()
    assert d.update(0.0, 0.0) is False


def test_detector_rising_motion_triggers_active():
    d = _make_detector(enter=5.0)
    assert d.update(6.0, 1.0) is True


def test_detector_does_not_trigger_below_enter():
    d = _make_detector(enter=5.0)
    assert d.update(4.9, 1.0) is False


def test_detector_stays_active_while_above_exit():
    d = _make_detector(enter=5.0, exit=2.0, grace=3.0)
    d.update(6.0, 0.0)   # → active
    for t in range(1, 10):
        result = d.update(3.0, float(t))   # above exit=2.0, stays active
        assert result is True


def test_detector_does_not_go_idle_within_grace():
    """Motion drops below exit but grace hasn't elapsed → still active."""
    d = _make_detector(enter=5.0, exit=2.0, grace=3.0)
    d.update(6.0, 0.0)  # → active
    d.update(1.0, 1.0)  # drops below exit; grace starts at t=1
    assert d.update(1.0, 3.9) is True  # only 2.9s elapsed, < 3.0 grace


def test_detector_goes_idle_after_grace():
    """Motion stays below exit for >= grace seconds → idle."""
    d = _make_detector(enter=5.0, exit=2.0, grace=3.0)
    d.update(6.0, 0.0)  # → active
    d.update(1.0, 1.0)  # drops below exit; grace starts at t=1
    result = d.update(1.0, 4.0)  # 3.0s elapsed == grace
    assert result is False


def test_detector_grace_reset_when_motion_rises():
    """Brief pause then motion rises above exit — grace timer cancels."""
    d = _make_detector(enter=5.0, exit=2.0, grace=3.0)
    d.update(6.0, 0.0)   # → active
    d.update(1.0, 1.0)   # drops below exit; grace starts
    d.update(3.0, 2.0)   # back above exit — grace cancelled
    d.update(1.0, 3.0)   # drops again; NEW grace timer starts at t=3
    assert d.update(1.0, 5.9) is True   # only 2.9s since t=3


def test_detector_idle_reactivates_on_motion():
    """Once idle, new motion above enter triggers active again."""
    d = _make_detector(enter=5.0, exit=2.0, grace=3.0)
    d.update(6.0, 0.0)   # → active
    d.update(1.0, 1.0)
    d.update(1.0, 4.0)   # → idle
    assert d.update(6.0, 5.0) is True  # re-activates


def test_detector_reset_clears_active_state():
    d = _make_detector()
    d.update(10.0, 0.0)  # → active
    d.reset()
    assert d.update(0.0, 1.0) is False  # back to idle after reset


def test_detector_ema_smoothing_delays_trigger():
    """With alpha=0.3, a single high spike does not immediately exceed enter=5."""
    # After 1 update with motion=10: EMA = 0.3*10 = 3.0 < 5.0 → still idle
    d = ActivityDetector(enter=5.0, exit=2.0, idle_grace_s=3.0, ema_alpha=0.3)
    assert d.update(10.0, 0.0) is False  # EMA only 3.0 after one tick


def test_detector_ema_accumulated_triggers():
    """Sustained motion accumulates in EMA until it crosses enter."""
    d = ActivityDetector(enter=5.0, exit=2.0, idle_grace_s=3.0, ema_alpha=0.3)
    # Each update: EMA = 0.3*10 + 0.7*prev
    # t=0: 3.0; t=1: 5.1 → active
    d.update(10.0, 0.0)
    assert d.update(10.0, 1.0) is True
