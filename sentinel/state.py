from __future__ import annotations

import threading
import time

from sentinel.classify import Posture, Status


class SharedState:
    """Thread-safe holder of the latest annotated JPEG + status + health."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._status = Status(Posture.AWAY, 0.0, 0.0, 0.0)
        self._healthy = False
        self._sitting_seconds = 0.0
        # Heartbeat: bumped every processing-loop iteration. The watchdog uses
        # loop_age() to detect a wedged loop (the loop can stall even while the
        # capture thread keeps producing fresh frames, so capture freshness
        # alone is not enough to prove the app is actually working).
        self._last_update_monotonic = time.monotonic()

    def update(self, jpeg: bytes, status: Status, healthy: bool, sitting_seconds: float):
        with self._lock:
            self._jpeg = jpeg
            self._status = status
            self._healthy = healthy
            self._sitting_seconds = sitting_seconds
            self._last_update_monotonic = time.monotonic()

    def loop_age(self) -> float:
        """Seconds since the processing loop last completed an iteration."""
        with self._lock:
            return time.monotonic() - self._last_update_monotonic

    def jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "posture": self._status.posture.value,
                "forward_head_deg": round(self._status.forward_head_deg, 1),
                "trunk_lean_deg": round(self._status.trunk_lean_deg, 1),
                "shoulder_drop": round(self._status.shoulder_drop, 3),
                "head_drop": round(self._status.head_drop, 3),
                "healthy": self._healthy,
                "sitting_seconds": round(self._sitting_seconds, 0),
                "active": self._status.active,
            }
