from __future__ import annotations

import json
import logging
import os
import threading
import time

from sentinel.classify import Posture, Status

log = logging.getLogger("desk_sentinel.state")


class SharedState:
    """Thread-safe holder of the latest annotated JPEG + status + health."""

    def __init__(self, mute_state_path: str | None = None):
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._status = Status(Posture.AWAY, 0.0, 0.0, 0.0)
        self._healthy = False
        self._sitting_seconds = 0.0
        # Mute: a plain on/off switch. Spoken nudges + notifications are
        # suppressed while muted, and it stays muted until explicitly turned
        # back on. Persisted to disk so a restart (the watchdog can trigger one
        # mid-meeting) never silently un-mutes.
        self._mute_state_path = mute_state_path
        self._muted = self._load_mute()
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

    # ── Mute (do-not-disturb) ─────────────────────────────────────────────
    def _load_mute(self) -> bool:
        if not self._mute_state_path:
            return False
        try:
            if os.path.exists(self._mute_state_path):
                with open(self._mute_state_path) as f:
                    return bool(json.load(f).get("muted", False))
        except Exception as exc:  # corrupt/unreadable -> default unmuted
            log.warning("could not read mute state: %s", exc)
        return False

    def _persist_mute(self) -> None:
        if not self._mute_state_path:
            return
        try:
            with open(self._mute_state_path, "w") as f:
                json.dump({"muted": self._muted}, f)
        except Exception as exc:  # non-fatal
            log.warning("could not persist mute state: %s", exc)

    def set_mute(self) -> None:
        """Mute nudges until explicitly unmuted (persists across restarts)."""
        with self._lock:
            self._muted = True
            self._persist_mute()

    def clear_mute(self) -> None:
        with self._lock:
            self._muted = False
            self._persist_mute()

    def is_muted(self) -> bool:
        with self._lock:
            return self._muted

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
                "muted": self._muted,
            }
