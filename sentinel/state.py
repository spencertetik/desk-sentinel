from __future__ import annotations

import threading

from sentinel.classify import Posture, Status


class SharedState:
    """Thread-safe holder of the latest annotated JPEG + status + health."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._status = Status(Posture.AWAY, 0.0, 0.0, 0.0)
        self._healthy = False
        self._sitting_seconds = 0.0

    def update(self, jpeg: bytes, status: Status, healthy: bool, sitting_seconds: float):
        with self._lock:
            self._jpeg = jpeg
            self._status = status
            self._healthy = healthy
            self._sitting_seconds = sitting_seconds

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
