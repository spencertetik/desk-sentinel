from __future__ import annotations

import threading
import time

import cv2


class RtspCapture:
    """Background RTSP reader holding only the most recent frame."""

    def __init__(self, url: str, target_fps: int = 8, stale_after: float = 8.0):
        # target_fps is accepted for call-site compatibility but the reader now
        # drains at the stream's native rate (the processing loop paces work);
        # throttling the reader here caused the decode buffer to back up.
        self._url = url
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._healthy = False
        self._frames_read = 0
        self._last_frame_monotonic = 0.0
        self._stale_after = stale_after  # is_healthy() False if no frame this long
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "RtspCapture":
        self._thread.start()
        return self

    def _open(self):
        # Force TCP transport, no buffering (freshest frame), and a socket I/O
        # timeout (microseconds) so read() can NEVER block forever on a stalled
        # RTSP stream — it returns failure, which triggers reconnect below.
        import os
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|timeout;15000000"
        )
        cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        # Best-effort: keep at most one decoded frame queued (no-op on some backends).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _run(self) -> None:
        cap = self._open()
        backoff = 1.0
        while not self._stop.is_set():
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None
            if not ok or frame is None:
                with self._lock:
                    self._healthy = False
                try:
                    cap.release()
                except Exception:
                    pass
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 15.0)
                cap = self._open()
                continue
            backoff = 1.0
            with self._lock:
                self._frame = frame
                self._healthy = True
                self._frames_read += 1
                self._last_frame_monotonic = time.monotonic()
            # No throttle sleep: drain at native rate so get_latest() stays current.
        cap.release()

    def get_latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def is_healthy(self) -> bool:
        # Truthful health: not just "last read succeeded", but "a frame arrived
        # recently". If read() wedges on a stalled stream, the frame ages out and
        # this flips False (so the dashboard shows stream-down and the watchdog
        # can act) instead of lying "healthy" on a frozen feed.
        with self._lock:
            if not self._healthy or self._last_frame_monotonic == 0.0:
                return False
            return (time.monotonic() - self._last_frame_monotonic) < self._stale_after

    def frame_age(self) -> float:
        """Seconds since the last fresh frame (inf if none yet)."""
        with self._lock:
            if self._last_frame_monotonic == 0.0:
                return float("inf")
            return time.monotonic() - self._last_frame_monotonic

    def frames_read(self) -> int:
        with self._lock:
            return self._frames_read

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
