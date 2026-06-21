import numpy as np

from sentinel.classify import Posture, Status
from sentinel.landmarks import Landmark, NUM_LANDMARKS
from sentinel.overlay import draw_overlay


def _blank():
    return np.zeros((480, 640, 3), dtype=np.uint8)


def test_draw_overlay_with_no_landmarks_returns_same_shape():
    frame = _blank()
    out = draw_overlay(frame, None, Status(Posture.AWAY, 0, 0, 0))
    assert out.shape == frame.shape


def test_draw_overlay_with_landmarks_draws_something():
    frame = _blank()
    pts = [Landmark(0.5, 0.5, 0.0, 0.9) for _ in range(NUM_LANDMARKS)]
    out = draw_overlay(frame, pts, Status(Posture.GOOD, 5, 4, 0.0))
    # something was drawn (non-zero pixels exist)
    assert out.sum() > 0
