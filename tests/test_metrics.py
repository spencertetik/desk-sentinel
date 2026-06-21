import math

from sentinel.landmarks import Landmark, LEFT_EAR, LEFT_SHOULDER, LEFT_HIP
from sentinel.metrics import angle_from_vertical, compute_posture
from tests.conftest import make_landmarks


def test_angle_from_vertical_pure_vertical_is_zero():
    a = Landmark(0.5, 0.2)
    b = Landmark(0.5, 0.6)
    assert angle_from_vertical(a, b) == 0.0


def test_angle_from_vertical_horizontal_is_ninety():
    a = Landmark(0.2, 0.5)
    b = Landmark(0.6, 0.5)
    assert abs(angle_from_vertical(a, b) - 90.0) < 1e-6


def test_angle_from_vertical_diagonal_is_fortyfive():
    a = Landmark(0.2, 0.2)
    b = Landmark(0.6, 0.6)
    assert abs(angle_from_vertical(a, b) - 45.0) < 1e-6


def test_upright_profile_has_small_angles(upright_left_profile):
    raw = compute_posture(upright_left_profile, min_visibility=0.5)
    assert raw.present is True
    assert raw.side == "left"
    assert raw.forward_head_deg < 5.0
    assert raw.trunk_lean_deg < 5.0
    assert abs(raw.shoulder_y - 0.40) < 1e-6
    assert abs(raw.ear_y - 0.20) < 1e-6


def test_forward_head_increases_angle():
    pts = make_landmarks({
        LEFT_EAR: Landmark(0.70, 0.20, 0.0, 0.99),      # ear pushed forward
        LEFT_SHOULDER: Landmark(0.50, 0.40, 0.0, 0.99),
        LEFT_HIP: Landmark(0.50, 0.80, 0.0, 0.99),
    }, default_vis=0.05)
    raw = compute_posture(pts, min_visibility=0.5)
    assert raw.side == "left"
    assert raw.forward_head_deg > 30.0


def test_absent_when_visibility_low():
    pts = make_landmarks({}, default_vis=0.05)
    raw = compute_posture(pts, min_visibility=0.5)
    assert raw.present is False
    assert raw.side == "none"
