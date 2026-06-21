"""Unit tests for sentinel.voice.brief.build_brief (pure, no DB)."""
from __future__ import annotations

import time

import pytest

from sentinel.voice.brief import build_brief, _fmt_duration, _fmt_time


# ---------------------------------------------------------------------------
# Helper: build a minimal canned stats dict
# ---------------------------------------------------------------------------

def _stats(
    present_seconds: float = 0,
    session_count: int = 0,
    first_sit_ts: float | None = None,
    last_leave_ts: float | None = None,
    good_pct: float = 0.0,
    bad_pct: float = 0.0,
    posture_samples: int = 0,
    breaks: int = 0,
    recent_days: list | None = None,
    current_posture: str | None = None,
    current_sitting_seconds: float | None = None,
    current_present: bool | None = None,
    bad_samples: int = 0,
) -> dict:
    return {
        "today_present_seconds": present_seconds,
        "today_breaks": breaks,
        "today_bad_samples": bad_samples,
        "today_bad_pct": bad_pct,
        "today_good_pct": good_pct,
        "today_posture_samples": posture_samples,
        "today_session_count": session_count,
        "today_first_sit_ts": first_sit_ts,
        "today_last_leave_ts": last_leave_ts,
        "recent_days": recent_days or [],
        "recent_events": [],
        "current_posture": current_posture,
        "current_sitting_seconds": current_sitting_seconds,
        "current_present": current_present,
    }


NOW = 1_750_000_000.0  # fixed "now" for deterministic tests


# ---------------------------------------------------------------------------
# _fmt_duration
# ---------------------------------------------------------------------------

def test_fmt_duration_hours_and_minutes():
    assert _fmt_duration(3 * 3600 + 12 * 60) == "3h 12m"


def test_fmt_duration_minutes_only():
    assert _fmt_duration(47 * 60) == "47m"


def test_fmt_duration_zero():
    assert _fmt_duration(0) == "0m"


def test_fmt_duration_exactly_one_hour():
    assert _fmt_duration(3600) == "1h 0m"


# ---------------------------------------------------------------------------
# build_brief — key facts in output
# ---------------------------------------------------------------------------

def test_build_brief_includes_desk_time():
    s = _stats(present_seconds=3 * 3600 + 12 * 60)
    brief = build_brief(s, NOW)
    assert "3h 12m" in brief


def test_build_brief_session_count():
    s = _stats(present_seconds=3600, session_count=4)
    brief = build_brief(s, NOW)
    assert "4" in brief  # session count is present


def test_build_brief_posture_good_pct():
    s = _stats(
        present_seconds=3600,
        session_count=1,
        good_pct=72.0,
        bad_pct=28.0,
        posture_samples=100,
    )
    brief = build_brief(s, NOW)
    assert "72.0%" in brief
    assert "28.0%" in brief


def test_build_brief_breaks():
    s = _stats(present_seconds=3600, breaks=3)
    brief = build_brief(s, NOW)
    assert "3" in brief  # breaks count appears


def test_build_brief_no_data_graceful():
    """An all-zeros stats dict must not raise and must return a string."""
    brief = build_brief(_stats(), NOW)
    assert isinstance(brief, str)
    assert len(brief) > 0
    # Should mention "none recorded yet" or similar
    assert "none" in brief.lower()


def test_build_brief_recent_days_included():
    days = [
        {"date": "2026-06-16", "seconds": 4 * 3600, "first_ts": 0.0, "last_ts": 0.0},
        {"date": "2026-06-15", "seconds": 5 * 3600 + 30 * 60, "first_ts": 0.0, "last_ts": 0.0},
    ]
    s = _stats(recent_days=days)
    brief = build_brief(s, NOW)
    assert "2026-06-16" in brief
    assert "4h" in brief
    assert "5h 30m" in brief


def test_build_brief_current_state_at_desk():
    s = _stats(
        current_posture="good",
        current_sitting_seconds=2700.0,
        current_present=True,
    )
    brief = build_brief(s, NOW)
    assert "At desk" in brief
    assert "good" in brief
    assert "45m" in brief  # 2700 s = 45m


def test_build_brief_current_state_away():
    s = _stats(current_present=False)
    brief = build_brief(s, NOW)
    assert "Away" in brief


def test_build_brief_no_current_state():
    """current_present=None → tracker-not-running message."""
    s = _stats()  # all current_* are None by default
    brief = build_brief(s, NOW)
    assert "unavailable" in brief.lower() or "not running" in brief.lower()


def test_build_brief_header_contains_date():
    """The brief must contain a date/time header."""
    brief = build_brief(_stats(), NOW)
    assert "Desk Sentinel Stats Brief" in brief


def test_build_brief_no_posture_samples():
    """When there are no posture samples, brief says no data."""
    s = _stats(posture_samples=0, good_pct=0.0, bad_pct=0.0)
    brief = build_brief(s, NOW)
    assert "no data" in brief.lower()


# ---------------------------------------------------------------------------
# Rollup history section
# ---------------------------------------------------------------------------

def _make_rollup(date: str, present_seconds: int, good_seconds: int,
                 active_seconds: int) -> dict:
    """Build a minimal rollup dict for testing."""
    return {
        "date": date,
        "present_seconds": present_seconds,
        "active_seconds": active_seconds,
        "idle_seconds": present_seconds - active_seconds,
        "good_seconds": good_seconds,
        "forward_head_seconds": 0,
        "slouching_seconds": 0,
        "sessions": 1,
        "breaks": 0,
        "first_sit_ts": None,
        "last_leave_ts": None,
        "work_seconds": present_seconds,
        "off_seconds": 0,
        "updated_ts": 0.0,
    }


def test_build_brief_with_rollups_includes_history_section():
    """Brief includes the recent-history section when rollups are present."""
    rollups = [
        _make_rollup("2026-06-11", 3 * 3600, 2 * 3600, 1800),
        _make_rollup("2026-06-12", 4 * 3600, 3 * 3600, 2400),
        _make_rollup("2026-06-13", 5 * 3600, 4 * 3600, 3000),
    ]
    s = _stats()
    s["rollups_30"] = rollups

    brief = build_brief(s, NOW)

    assert "RECENT HISTORY" in brief
    assert "2026-06-11" in brief
    assert "2026-06-12" in brief
    assert "2026-06-13" in brief


def test_build_brief_rollups_30_day_averages():
    """Brief includes 30-day averages section with avg desk hrs and posture."""
    rollups = [
        _make_rollup("2026-06-11", 4 * 3600, 2 * 3600, 2000),
        _make_rollup("2026-06-12", 4 * 3600, 2 * 3600, 2000),
    ]
    s = _stats()
    s["rollups_30"] = rollups

    brief = build_brief(s, NOW)

    assert "30-DAY AVERAGES" in brief
    assert "Avg desk time/day" in brief
    assert "Avg posture-good" in brief
    assert "Avg active" in brief


def test_build_brief_rollup_posture_good_pct():
    """Per-day posture-good % is included in the history section."""
    # 3600 present, 1800 good → 50%
    rollups = [_make_rollup("2026-06-11", 3600, 1800, 0)]
    s = _stats()
    s["rollups_30"] = rollups

    brief = build_brief(s, NOW)

    assert "50.0%" in brief


def test_build_brief_no_rollups_graceful():
    """Brief with no rollups (key absent or empty) does not raise and omits history section."""
    s = _stats()
    # Key absent entirely
    brief_no_key = build_brief(s, NOW)
    assert isinstance(brief_no_key, str)
    assert "RECENT HISTORY" not in brief_no_key

    # Key present but empty
    s["rollups_30"] = []
    brief_empty = build_brief(s, NOW)
    assert isinstance(brief_empty, str)
    assert "RECENT HISTORY" not in brief_empty


def test_build_brief_rollups_last_7_in_history():
    """With 10 rollup days, the history section shows only the last 7."""
    rollups = [
        _make_rollup(f"2026-06-{i:02d}", 3600, 1800, 0)
        for i in range(1, 11)  # 2026-06-01 through 2026-06-10
    ]
    s = _stats()
    s["rollups_30"] = rollups

    brief = build_brief(s, NOW)

    # Last 7: Jun 04-10 should appear; Jun 01-03 should NOT
    for day in range(4, 11):
        assert f"2026-06-{day:02d}" in brief
    for day in range(1, 4):
        assert f"2026-06-{day:02d}" not in brief
