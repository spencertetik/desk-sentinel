from __future__ import annotations

import logging
import subprocess
import time
from typing import Callable

log = logging.getLogger("desk_sentinel.nudges")


def speak_mac(message: str, volume: int | None) -> None:
    """Speak a message locally on macOS, optionally setting output volume first."""
    try:
        if volume is not None:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {int(volume)}"],
                check=False, timeout=5,
            )
        subprocess.run(["say", message], check=False, timeout=30)
    except Exception as exc:  # non-fatal
        log.warning("speak failed: %s", exc)


def notify_mac(title: str, message: str) -> None:
    # Pass message/title as runtime arguments rather than interpolating them
    # into the AppleScript source. Building the script with json.dumps emitted
    # \uXXXX escapes for any non-ASCII character (curly quotes, emoji, etc.),
    # which AppleScript rejects with a syntax error (-2741). argv avoids all
    # string-escaping concerns.
    try:
        subprocess.run(
            [
                "osascript",
                "-e", "on run argv",
                "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
                "-e", "end run",
                message, title,
            ],
            check=False, timeout=5,
        )
    except Exception as exc:  # non-fatal
        log.warning("notify failed: %s", exc)


class Nudger:
    """Gates events by active window + per-type cooldown, then dispatches a
    local spoken nudge and a desktop notification. `now` is supplied by the
    caller (epoch seconds) so behavior is testable.

    Active window is defined by fractional hours (e.g. 8.5 = 8:30am) to
    support half-hour boundaries.
    """

    def __init__(
        self,
        work_start_hour: float,
        work_end_hour: float,
        cooldown_seconds: dict[str, int],
        default_cooldown_seconds: int,
        speak_volume: int | None,
        speak_fn: Callable[[str, "int | None"], None] = speak_mac,
        notify_fn: Callable[[str, str], None] = notify_mac,
    ):
        self._start = work_start_hour
        self._end = work_end_hour
        self._cooldowns = cooldown_seconds
        self._default_cooldown = default_cooldown_seconds
        self._speak_volume = speak_volume
        self._speak = speak_fn
        self._notify = notify_fn
        self._last_fired: dict[str, float] = {}

    def _in_active_window(self, now: float) -> bool:
        lt = time.localtime(now)
        fractional_hour = lt.tm_hour + lt.tm_min / 60.0
        return self._start <= fractional_hour < self._end

    def dispatch(self, event, now: float) -> bool:
        if not event.message:
            return False
        if not self._in_active_window(now):
            return False
        cd = self._cooldowns.get(event.type, self._default_cooldown)
        last = self._last_fired.get(event.type)
        if last is not None and now - last < cd:
            return False
        self._last_fired[event.type] = now
        self._notify("Desk Sentinel", event.message)
        self._speak(event.message, self._speak_volume)
        return True
