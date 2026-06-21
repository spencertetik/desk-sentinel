from __future__ import annotations

import time
from dataclasses import dataclass

from sentinel.classify import Posture, Status

_BAD = (Posture.FORWARD_HEAD, Posture.SLOUCHING)

_MESSAGES = {
    "break_due": "You've been sitting for an hour. Time to stand up.",
    "poor_posture_sustained": "Check your posture.",
    "returned": "Welcome back.",
    "left_desk": "",
    "posture_slipping": "Ease back — your posture's slipping.",
    "posture_good_streak": "Nice — solid posture for a while now.",
    "periodic_checkin": "Check in: you've been at the desk a while.",
    # Bookend events — messages overridden by app.py with composed content
    "morning_arrival": "",
    "wind_down": "",
}


@dataclass(frozen=True)
class Event:
    type: str
    ts: float
    message: str


class EventEngine:
    """Consumes a stream of (Status, now) and emits posture/activity events.

    Pure stateful logic: ``now`` is supplied by the caller, so it is fully
    testable without real time.

    Presence debounce
    -----------------
    A ``returned`` / ``left_desk`` transition fires only after the raw
    present/away state is *sustained* for ``debounce_seconds`` (default 4).
    Flickers shorter than that emit nothing.  All per-frame timers (sit,
    posture) key off the debounced/committed state, not the raw frame value.

    New events (Coach v2)
    ---------------------
    ``posture_slipping``
        Bad posture (FORWARD_HEAD or SLOUCHING) sustained continuously >=
        ``posture_slip_seconds`` while present.  Fires once, re-arms on
        recovery to good posture.  Independent of ``poor_posture_sustained``;
        fires earlier by default (~90 s vs ~300 s).

    ``posture_good_streak``
        Good posture sustained continuously >= ``good_streak_seconds`` while
        present.  Fires once per streak, re-arms when posture degrades.

    ``periodic_checkin``
        Every ``checkin_interval_seconds`` of continuous (debounced)
        presence.  Counter resets on ``left_desk``.

    Daily bookends
    --------------
    ``morning_arrival``
        Fires once per local day on the first committed-present tick whose
        local date differs from ``_last_briefing_date`` AND whose local
        fractional hour >= ``morning_after_hour`` (default 5.0, to skip
        3am bathroom trips).

    ``wind_down``
        Fires once per local day while committed present when local fractional
        hour >= (``work_end_hour`` - ``wind_down_lead_minutes`` / 60).
    """

    def __init__(
        self,
        break_after_seconds: int,
        poor_posture_seconds: int,
        debounce_seconds: int = 4,
        posture_slip_seconds: int = 90,
        good_streak_seconds: int = 1200,
        checkin_interval_seconds: int = 3600,
        # Daily bookend params
        morning_after_hour: float = 5.0,
        work_end_hour: float = 17.5,
        wind_down_lead_minutes: int = 30,
    ):
        self._break_after = break_after_seconds
        self._posture_after = poor_posture_seconds
        self._debounce = debounce_seconds
        self._slip_after = posture_slip_seconds
        self._streak_after = good_streak_seconds
        self._checkin_interval = checkin_interval_seconds

        # Bookend params
        self._morning_after_hour = morning_after_hour
        self._wind_down_trigger = work_end_hour - wind_down_lead_minutes / 60.0

        # Debounce state
        self._committed_present: bool = False
        self._pending_present: bool | None = None
        self._pending_start: float | None = None

        # Sit timer (keys off committed state)
        self._sit_start: float | None = None
        self._break_fired: bool = False

        # Bad-posture timers (shared start; separate fired flags)
        self._bad_start: float | None = None
        self._posture_fired: bool = False   # poor_posture_sustained
        self._slip_fired: bool = False      # posture_slipping

        # Good-streak timer
        self._good_start: float | None = None
        self._good_fired: bool = False

        # Periodic check-in timer
        self._last_checkin: float | None = None   # set to now on each committed return

        # Daily bookend guards (local date strings, e.g. "2026-06-17")
        self._last_briefing_date: str | None = None
        self._last_winddown_date: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, type_: str, now: float) -> Event:
        return Event(type_, now, _MESSAGES.get(type_, ""))

    def _reset_present_timers(self, now: float) -> None:
        """Reset all per-session timers; call when committed state becomes present."""
        self._sit_start = now
        self._break_fired = False
        self._bad_start = None
        self._posture_fired = False
        self._slip_fired = False
        self._good_start = None
        self._good_fired = False
        self._last_checkin = now

    def _reset_away_timers(self) -> None:
        """Clear all per-session timers; call when committed state becomes away."""
        self._sit_start = None
        self._break_fired = False
        self._bad_start = None
        self._posture_fired = False
        self._slip_fired = False
        self._good_start = None
        self._good_fired = False
        self._last_checkin = None

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    def update(self, status: Status, now: float) -> list[Event]:
        events: list[Event] = []
        raw_present = status.posture is not Posture.AWAY

        # --- Debounce: advance pending/committed state ----------------
        transition_happened = False
        if raw_present != self._committed_present:
            # Raw state differs from committed — candidate transition
            if self._pending_present != raw_present:
                # New direction; start tracking
                self._pending_present = raw_present
                self._pending_start = now
            # Check if sustained long enough (works for debounce_seconds=0 too)
            if now - self._pending_start >= self._debounce:  # type: ignore[operator]
                self._committed_present = raw_present
                self._pending_present = None
                self._pending_start = None
                transition_happened = True
        else:
            # Raw matches committed — clear any pending candidate
            self._pending_present = None
            self._pending_start = None

        # --- Handle committed transitions ----------------------------
        if transition_happened:
            if self._committed_present:
                events.append(self._emit("returned", now))
                self._reset_present_timers(now)
            else:
                events.append(self._emit("left_desk", now))
                self._reset_away_timers()

        # --- Per-frame timers (only while committed present) ---------
        if self._committed_present:
            # Sit timer -> break_due
            if self._sit_start is None:
                self._sit_start = now
            if not self._break_fired and now - self._sit_start >= self._break_after:
                events.append(self._emit("break_due", now))
                self._break_fired = True

            # Bad-posture timers (posture_slipping + poor_posture_sustained)
            if status.posture in _BAD:
                if self._bad_start is None:
                    self._bad_start = now
                elapsed_bad = now - self._bad_start
                if not self._slip_fired and elapsed_bad >= self._slip_after:
                    events.append(self._emit("posture_slipping", now))
                    self._slip_fired = True
                if not self._posture_fired and elapsed_bad >= self._posture_after:
                    events.append(self._emit("poor_posture_sustained", now))
                    self._posture_fired = True
            else:
                # Posture recovered (good, or transient AWAY while committed)
                self._bad_start = None
                self._posture_fired = False
                self._slip_fired = False

            # Good-streak timer
            if status.posture is Posture.GOOD:
                if self._good_start is None:
                    self._good_start = now
                if not self._good_fired and now - self._good_start >= self._streak_after:
                    events.append(self._emit("posture_good_streak", now))
                    self._good_fired = True
            else:
                self._good_start = None
                self._good_fired = False

            # Periodic check-in
            if (
                self._last_checkin is not None
                and now - self._last_checkin >= self._checkin_interval
            ):
                events.append(self._emit("periodic_checkin", now))
                self._last_checkin = now

            # --- Daily bookends (committed present only) --------------
            lt = time.localtime(now)
            today = time.strftime("%Y-%m-%d", lt)
            frac_hour = lt.tm_hour + lt.tm_min / 60.0

            # morning_arrival: first present tick of a new day, after morning_after_hour
            if (
                frac_hour >= self._morning_after_hour
                and self._last_briefing_date != today
            ):
                self._last_briefing_date = today
                events.append(self._emit("morning_arrival", now))

            # wind_down: once per day when fractional hour reaches trigger while present
            if (
                frac_hour >= self._wind_down_trigger
                and self._last_winddown_date != today
            ):
                self._last_winddown_date = today
                events.append(self._emit("wind_down", now))

        return events
