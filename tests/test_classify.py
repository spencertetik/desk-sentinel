from sentinel.calibration import Baseline
from sentinel.classify import Posture, classify
from sentinel.config import Thresholds
from sentinel.metrics import RawPosture


BASE = Baseline(forward_head_deg=5.0, trunk_lean_deg=4.0, shoulder_y=0.40, ear_y=0.30)
THR = Thresholds()


def _raw(fh, tr, sy=0.40, present=True, ear_y=0.30):
    return RawPosture(fh, tr, sy, present=present, side="left", ear_y=ear_y)


def test_absent_is_away():
    st = classify(_raw(0, 0, present=False), BASE, THR)
    assert st.posture is Posture.AWAY


def test_near_baseline_is_good():
    st = classify(_raw(6.0, 5.0), BASE, THR)
    assert st.posture is Posture.GOOD


def test_forward_head_when_over_margin():
    st = classify(_raw(5.0 + THR.forward_head_margin_deg + 1, 5.0), BASE, THR)
    assert st.posture is Posture.FORWARD_HEAD


def test_head_drop_triggers_slouching():
    # head dropped well below the calibrated neutral ear height
    st = classify(_raw(6.0, 5.0, ear_y=0.30 + THR.head_drop_margin + 0.03), BASE, THR)
    assert st.posture is Posture.SLOUCHING
    assert st.head_drop > THR.head_drop_margin


def test_small_head_drop_stays_good():
    st = classify(_raw(6.0, 5.0, ear_y=0.30 + THR.head_drop_margin - 0.01), BASE, THR)
    assert st.posture is Posture.GOOD


def test_head_drop_is_zero_without_baseline():
    st = classify(_raw(6.0, 5.0, ear_y=0.55), None, THR)
    assert st.head_drop == 0.0  # relative metric needs calibration


def test_shoulder_drop_is_relative_to_baseline():
    st = classify(_raw(6.0, 5.0, sy=0.46), BASE, THR)
    assert abs(st.shoulder_drop - 0.06) < 1e-6


def test_no_baseline_uses_absolute_fallback():
    st = classify(_raw(THR.abs_forward_head_deg + 1, 5.0), None, THR)
    assert st.posture is Posture.FORWARD_HEAD
    assert st.shoulder_drop == 0.0
