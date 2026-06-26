"""sentinel/liveness.py — reject frozen (furniture) pose detections.

MediaPipe will hallucinate a person on static furniture (an empty desk chair),
and such a detection sits perfectly still. A real person is never motionless for
long — they shift, turn, breathe, reach. This tracker confirms a detected body
is *alive* by requiring its pose to move across a rolling time window.

Pure logic (positions + timestamps), so it is fully unit-testable.
"""
from __future__ import annotations

from collections import deque


class PresenceLiveness:
    """Gate a present pose on whether it has actually moved recently.

    update(present, x, y, now) -> bool (alive)

    - ``present`` False clears history and returns False.
    - A *teleport* (the detected shoulder jumping more than ``teleport`` in one
      step) means the subject switched — e.g. the real person left and the
      detector latched onto the empty chair, or vice-versa — so history is reset
      and the new subject must prove liveness on its own.
    - ``alive`` is True once the position's range (max−min of x or y) over the
      window exceeds ``move_delta``. A frozen phantom never reaches it; a real
      person clears it within seconds of normal movement.
    """

    def __init__(
        self,
        window_s: float = 120.0,
        move_delta: float = 0.06,
        teleport: float = 0.15,
    ):
        self._window_s = window_s
        self._move_delta = move_delta
        self._teleport = teleport
        self._hist: deque[tuple[float, float, float]] = deque()
        self._last: tuple[float, float] | None = None

    def update(self, present: bool, x: float, y: float, now: float) -> bool:
        if not present:
            self._hist.clear()
            self._last = None
            return False

        if self._last is not None and (
            abs(x - self._last[0]) > self._teleport
            or abs(y - self._last[1]) > self._teleport
        ):
            # Subject switched (real person <-> furniture). Restart the proof.
            self._hist.clear()

        self._last = (x, y)
        self._hist.append((now, x, y))

        cutoff = now - self._window_s
        while self._hist and self._hist[0][0] < cutoff:
            self._hist.popleft()

        xs = [p[1] for p in self._hist]
        ys = [p[2] for p in self._hist]
        rng = max(max(xs) - min(xs), max(ys) - min(ys))
        return rng > self._move_delta
