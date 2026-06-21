from __future__ import annotations

import cv2

from sentinel.classify import Posture, Status
from sentinel.landmarks import Landmark

# Pose connections to draw (subset that matters for posture).
_CONNECTIONS = [
    (7, 11), (8, 12),     # ear -> shoulder
    (11, 12),             # shoulder line
    (11, 23), (12, 24),   # shoulder -> hip
    (23, 24),             # hip line
    (11, 13), (13, 15),   # left arm
    (12, 14), (14, 16),   # right arm
]

_COLORS = {
    Posture.GOOD: (80, 220, 120),
    Posture.FORWARD_HEAD: (60, 160, 255),
    Posture.SLOUCHING: (60, 60, 255),
    Posture.AWAY: (160, 160, 160),
}

# ROI overlay colors (BGR): green when active, neutral grey when idle/away
_ROI_ACTIVE_COLOR = (60, 220, 80)    # green-ish
_ROI_IDLE_COLOR   = (100, 100, 100)  # neutral grey


def draw_overlay(
    frame_bgr,
    landmarks: list[Landmark] | None,
    status: Status,
    roi: list[float] | None = None,
):
    """Draw pose skeleton, status label, and optionally the activity ROI rectangle.

    roi: normalised [x0, y0, x1, y1]; drawn faintly so the controller can
    verify the region covers the keyboard/desk area.  Tinted green when
    status.active=True, neutral grey when idle or away.
    """
    out = frame_bgr.copy()
    h, w = out.shape[:2]
    color = _COLORS.get(status.posture, (200, 200, 200))

    if landmarks is not None:
        def px(i):
            return int(landmarks[i].x * w), int(landmarks[i].y * h)
        for a, b in _CONNECTIONS:
            cv2.line(out, px(a), px(b), color, 2, cv2.LINE_AA)
        for i in (7, 8, 11, 12, 23, 24):
            cv2.circle(out, px(i), 4, color, -1, cv2.LINE_AA)

    label = status.posture.value.replace("_", " ").upper()
    cv2.rectangle(out, (0, 0), (w, 64), (0, 0, 0), -1)
    cv2.putText(out, label, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)
    readout = f"head {status.forward_head_deg:4.1f}  trunk {status.trunk_lean_deg:4.1f}"
    cv2.putText(out, readout, (16, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1, cv2.LINE_AA)

    # Activity ROI rectangle — faint border so the controller can see/tune it.
    if roi is not None:
        try:
            rx0 = int(max(0.0, min(roi[0], 1.0)) * w)
            ry0 = int(max(0.0, min(roi[1], 1.0)) * h)
            rx1 = int(max(0.0, min(roi[2], 1.0)) * w)
            ry1 = int(max(0.0, min(roi[3], 1.0)) * h)
            if rx1 > rx0 and ry1 > ry0:
                roi_color = _ROI_ACTIVE_COLOR if status.active else _ROI_IDLE_COLOR
                cv2.rectangle(out, (rx0, ry0), (rx1, ry1), roi_color, 1, cv2.LINE_AA)
                act_label = "ACTIVE" if status.active else "IDLE"
                cv2.putText(
                    out, act_label,
                    (rx0 + 4, ry0 + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, roi_color, 1, cv2.LINE_AA,
                )
        except Exception:
            pass  # malformed ROI — never crash the overlay

    return out
