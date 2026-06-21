from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("desk_sentinel.activity")


def roi_motion(
    prev_gray: "np.ndarray | None",
    cur_gray: "np.ndarray",
    roi: list,
) -> float:
    """Mean absolute pixel difference inside a normalized ROI.

    roi = [x0, y0, x1, y1] in normalised coords [0.0, 1.0].
    Coords are clamped to frame dimensions; empty crop returns 0.

    prev_gray may be None on the very first tick (returns 0, starts idle).
    Uses int16 to avoid uint8 wrap-around artifacts.
    Note: caller passes the ORIGINAL capture frame (not the pose-downscale),
    so this function works at full camera resolution for maximum accuracy.
    """
    if prev_gray is None:
        return 0.0

    h, w = cur_gray.shape[:2]

    x0 = int(max(0.0, min(roi[0], 1.0)) * w)
    y0 = int(max(0.0, min(roi[1], 1.0)) * h)
    x1 = int(max(0.0, min(roi[2], 1.0)) * w)
    y1 = int(max(0.0, min(roi[3], 1.0)) * h)

    if x1 <= x0 or y1 <= y0:
        return 0.0

    prev_crop = prev_gray[y0:y1, x0:x1]
    cur_crop = cur_gray[y0:y1, x0:x1]

    return float(np.mean(np.abs(cur_crop.astype(np.int16) - prev_crop.astype(np.int16))))


class ActivityDetector:
    """Hysteretic activity detector with EMA smoothing + idle-grace timer.

    Transitions:
      idle -> active  when smoothed motion > enter
      active -> idle  when smoothed motion < exit sustained >= idle_grace_s

    Clock is injected via update(motion, now) for testability.
    Call reset() when the user goes AWAY to clear stale grace-timer state.
    """

    def __init__(
        self,
        enter: float,
        exit: float,
        idle_grace_s: float,
        ema_alpha: float,
    ) -> None:
        self._enter = enter
        self._exit = exit
        self._grace = idle_grace_s
        self._alpha = ema_alpha

        self._ema: float = 0.0
        self._active: bool = False
        self._below_exit_since: "float | None" = None

    def update(self, motion: float, now: float) -> bool:
        """Ingest current motion score; return updated active flag."""
        self._ema = self._alpha * motion + (1.0 - self._alpha) * self._ema

        if not self._active:
            if self._ema > self._enter:
                self._active = True
                self._below_exit_since = None
        else:
            if self._ema < self._exit:
                if self._below_exit_since is None:
                    self._below_exit_since = now
                elif now - self._below_exit_since >= self._grace:
                    self._active = False
                    self._below_exit_since = None
            else:
                self._below_exit_since = None

        return self._active

    def reset(self) -> None:
        """Reset all state.  Call when the user goes AWAY."""
        self._ema = 0.0
        self._active = False
        self._below_exit_since = None
