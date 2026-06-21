"""Tests for the daily bookend events: morning_arrival and wind_down.

Uses real epoch timestamps (fixed calendar date) so localtime() returns
predictable values regardless of the host timezone offset.  The key is
that we test relative behaviour (fires / doesn't fire) rather than
absolute UTC times, so any timezone that keeps the test hours within a
single calendar day will pass.

Strategy
--------
* Use 2026-06-17 as the fixture date.
* morning_after_hour=6.0 so a tick at local 8:00 on that date fires.
* wind_down_trigger = work_end_hour - lead/60 = 17.0 - 0.5 = 16.5 (4:30pm).
  Tick at 16:30 fires; tick at 16:29 does not.
* All posture / break / periodic-checkin events are suppressed via
  huge threshold values so we only observe bookend events.
"""
from __future__ import annotations

import time

import pytest

from sentinel.classify import Posture, Status
from sentinel.events import EventEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _st(posture=Posture.GOOD):
    return Status(posture, 0.0, 0.0, 0.0)


def _ts(hour: int, minute: int = 0, date=(2026, 6, 17)) -> float:
    """Return a float epoch for the given local date+time."""
    y, mo, d = date
    return time.mktime((y, mo, d, hour, minute, 0, 0, 0, -1))


def _bookend_engine(
    morning_after_hour: float = 6.0,
    work_end_hour: float = 17.0,
    wind_down_lead_minutes: int = 30,
    debounce_seconds: int = 0,   # instant commits for simpler test setup
):
    """Engine with bookends active and everything else suppressed."""
    return EventEngine(
        break_after_seconds=100_000,
        poor_posture_seconds=100_000,
        debounce_seconds=debounce_seconds,
        posture_slip_seconds=100_000,
        good_streak_seconds=100_000,
        checkin_interval_seconds=100_000,
        morning_after_hour=morning_after_hour,
        work_end_hour=work_end_hour,
        wind_down_lead_minutes=wind_down_lead_minutes,
    )


def _types(events):
    return [e.type for e in events]


# ---------------------------------------------------------------------------
# morning_arrival
# ---------------------------------------------------------------------------

class TestMorningArrival:

    def test_fires_on_first_present_tick_after_morning_hour(self):
        """First committed-present tick at 8:00 (> morning_after_hour=6.0) fires."""
        eng = _bookend_engine()
        ts = _ts(8, 0)
        evts = eng.update(_st(), ts)
        assert "morning_arrival" in _types(evts)

    def test_does_not_fire_before_morning_after_hour(self):
        """Tick at 5:00 (< morning_after_hour=6.0) does not fire morning_arrival."""
        eng = _bookend_engine(morning_after_hour=6.0)
        ts = _ts(5, 0)
        evts = eng.update(_st(), ts)
        assert "morning_arrival" not in _types(evts)

    def test_fires_exactly_at_morning_after_hour(self):
        """Tick exactly at morning_after_hour=6.0 fires (>= boundary)."""
        eng = _bookend_engine(morning_after_hour=6.0)
        ts = _ts(6, 0)
        evts = eng.update(_st(), ts)
        assert "morning_arrival" in _types(evts)

    def test_fires_only_once_per_day(self):
        """Second tick on the same day does not fire morning_arrival again."""
        eng = _bookend_engine()
        ts1 = _ts(8, 0)
        ts2 = _ts(9, 0)
        eng.update(_st(), ts1)   # fires
        evts2 = eng.update(_st(), ts2)
        assert "morning_arrival" not in _types(evts2)

    def test_does_not_fire_while_away(self):
        """morning_arrival requires committed present; AWAY ticks don't trigger."""
        eng = _bookend_engine()
        ts = _ts(8, 0)
        evts = eng.update(_st(Posture.AWAY), ts)
        assert "morning_arrival" not in _types(evts)

    def test_fires_again_on_next_day(self):
        """After firing on day 1, fires again on the first present tick of day 2."""
        eng = _bookend_engine()
        # Day 1
        ts_d1 = _ts(8, 0, date=(2026, 6, 17))
        eng.update(_st(), ts_d1)  # fires day 1

        # Day 2
        ts_d2 = _ts(8, 0, date=(2026, 6, 18))
        evts = eng.update(_st(), ts_d2)
        assert "morning_arrival" in _types(evts)

    def test_resets_after_midnight_gap(self):
        """Engine that has fired on day 1 resets guard for day 2."""
        eng = _bookend_engine()
        # Day 1: fire
        eng.update(_st(), _ts(8, 0, date=(2026, 6, 17)))
        # Day 1 again (same day): no second fire
        evts_same = eng.update(_st(), _ts(10, 0, date=(2026, 6, 17)))
        assert "morning_arrival" not in _types(evts_same)
        # Day 2: fires again
        evts_d2 = eng.update(_st(), _ts(9, 0, date=(2026, 6, 18)))
        assert "morning_arrival" in _types(evts_d2)


# ---------------------------------------------------------------------------
# wind_down
# ---------------------------------------------------------------------------

class TestWindDown:
    """wind_down_trigger = work_end_hour(17.0) - lead(30)/60 = 16.5 (4:30pm)."""

    def test_fires_at_trigger_time(self):
        """Tick at exactly the trigger fractional hour fires wind_down."""
        eng = _bookend_engine(work_end_hour=17.0, wind_down_lead_minutes=30)
        # trigger = 17.0 - 0.5 = 16.5 → 16:30
        ts = _ts(16, 30)
        evts = eng.update(_st(), ts)
        assert "wind_down" in _types(evts)

    def test_does_not_fire_before_trigger(self):
        """Tick at 16:29 (fractional 16.483) < trigger 16.5 → no wind_down."""
        eng = _bookend_engine(work_end_hour=17.0, wind_down_lead_minutes=30)
        ts = _ts(16, 29)
        evts = eng.update(_st(), ts)
        assert "wind_down" not in _types(evts)

    def test_fires_only_once_per_day(self):
        """Second tick past the trigger on the same day does not fire again."""
        eng = _bookend_engine(work_end_hour=17.0, wind_down_lead_minutes=30)
        ts1 = _ts(16, 30)
        ts2 = _ts(16, 45)
        eng.update(_st(), ts1)   # fires
        evts2 = eng.update(_st(), ts2)
        assert "wind_down" not in _types(evts2)

    def test_does_not_fire_while_away(self):
        """wind_down requires committed present; AWAY ticks don't trigger."""
        eng = _bookend_engine(work_end_hour=17.0, wind_down_lead_minutes=30)
        ts = _ts(16, 30)
        evts = eng.update(_st(Posture.AWAY), ts)
        assert "wind_down" not in _types(evts)

    def test_fires_again_on_next_day(self):
        """Fires again on the next calendar day."""
        eng = _bookend_engine(work_end_hour=17.0, wind_down_lead_minutes=30)
        eng.update(_st(), _ts(16, 30, date=(2026, 6, 17)))  # day 1
        evts = eng.update(_st(), _ts(16, 30, date=(2026, 6, 18)))
        assert "wind_down" in _types(evts)

    def test_morning_arrival_and_wind_down_same_day_independent(self):
        """Both events can fire on the same day without interfering."""
        eng = _bookend_engine(morning_after_hour=6.0, work_end_hour=17.0, wind_down_lead_minutes=30)
        morning_evts = eng.update(_st(), _ts(8, 0))
        evening_evts = eng.update(_st(), _ts(16, 30))

        assert "morning_arrival" in _types(morning_evts)
        assert "wind_down" in _types(evening_evts)

        # Neither fires again same day
        assert "morning_arrival" not in _types(eng.update(_st(), _ts(9, 0)))
        assert "wind_down" not in _types(eng.update(_st(), _ts(17, 0)))
