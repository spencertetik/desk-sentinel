"""Tests for Store.rollup_day, recent_rollups, and rollups_between."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from sentinel.classify import Posture, Status
from sentinel.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_on_date(date_str: str, hour: int = 10, minute: int = 0, second: int = 0) -> float:
    """Return a float timestamp for a given local date and hour."""
    t = time.strptime(date_str, "%Y-%m-%d")
    return time.mktime(
        (t.tm_year, t.tm_mon, t.tm_mday, hour, minute, second, 0, 0, -1)
    )


def _add_present(store: Store, ts: float, posture: Posture = Posture.GOOD,
                 active: int = 1) -> None:
    status = Status(posture, 0.0, 0.0, 0.0)
    # Manually insert so we can control active flag
    store._conn.execute(
        "INSERT INTO metrics_samples "
        "(ts, forward_head_deg, trunk_lean_deg, shoulder_drop, posture, present, active) "
        "VALUES (?, 0, 0, 0, ?, 1, ?)",
        (ts, posture.value, active),
    )
    store._conn.commit()


def _add_away(store: Store, ts: float) -> None:
    store._conn.execute(
        "INSERT INTO metrics_samples "
        "(ts, forward_head_deg, trunk_lean_deg, shoulder_drop, posture, present, active) "
        "VALUES (?, 0, 0, 0, 'away', 0, 0)",
        (ts,),
    )
    store._conn.commit()


def _add_break_event(store: Store, ts: float) -> None:
    store._conn.execute(
        "INSERT INTO events (ts, type, message) VALUES (?, 'break_due', 'Take a break')",
        (ts,),
    )
    store._conn.commit()


# ---------------------------------------------------------------------------
# rollup_day — basic aggregates
# ---------------------------------------------------------------------------

def test_rollup_day_present_active_idle(tmp_path: Path):
    """rollup_day correctly counts present/active/idle seconds."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"
    base = _ts_on_date(date, hour=9)

    # 3 present+active, 2 present+idle, 1 away
    for i in range(3):
        _add_present(store, base + i, active=1)
    for i in range(2):
        _add_present(store, base + 100 + i, active=0)
    _add_away(store, base + 200)

    r = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    assert r["present_seconds"] == 5
    assert r["active_seconds"] == 3
    assert r["idle_seconds"] == 2
    store.close()


def test_rollup_day_posture_counts(tmp_path: Path):
    """rollup_day counts posture seconds correctly."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"
    base = _ts_on_date(date, hour=10)

    _add_present(store, base, posture=Posture.GOOD)
    _add_present(store, base + 1, posture=Posture.GOOD)
    _add_present(store, base + 2, posture=Posture.SLOUCHING)
    _add_present(store, base + 3, posture=Posture.FORWARD_HEAD)

    r = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    assert r["good_seconds"] == 2
    assert r["slouching_seconds"] == 1
    assert r["forward_head_seconds"] == 1
    store.close()


def test_rollup_day_breaks(tmp_path: Path):
    """rollup_day counts break_due events."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"
    base = _ts_on_date(date, hour=11)

    _add_present(store, base)
    _add_break_event(store, base + 1)
    _add_break_event(store, base + 2)

    r = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    assert r["breaks"] == 2
    store.close()


def test_rollup_day_sessions(tmp_path: Path):
    """rollup_day computes session count and first/last timestamps.

    Sessions must be >= min_session_s=30s to survive sessionize filtering.
    We seed two ~60s sessions separated by a 50s away gap (> merge threshold).
    """
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"
    base = _ts_on_date(date, hour=9)

    # Session 1: 60 present samples at 9:00 (seconds 0..59) — survives 30s filter
    for i in range(60):
        _add_present(store, base + i)
    # Away gap: 50 seconds (> 20s merge threshold, so splits into 2 sessions)
    for i in range(50):
        _add_away(store, base + 60 + i)
    # Session 2: 60 present samples at 9:01:50 — survives 30s filter
    for i in range(60):
        _add_present(store, base + 110 + i)

    r = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    assert r["sessions"] == 2
    assert r["first_sit_ts"] is not None
    assert r["last_leave_ts"] is not None
    assert r["first_sit_ts"] < r["last_leave_ts"]
    store.close()


def test_rollup_day_work_off_seconds(tmp_path: Path):
    """rollup_day correctly splits present seconds into work vs off hours."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"

    # 3 samples during work hours (10am)
    work_ts = _ts_on_date(date, hour=10)
    for i in range(3):
        _add_present(store, work_ts + i)

    # 2 samples outside work hours (7am)
    off_ts = _ts_on_date(date, hour=7)
    for i in range(2):
        _add_present(store, off_ts + i)

    r = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    assert r["work_seconds"] == 3
    assert r["off_seconds"] == 2
    store.close()


def test_rollup_day_empty_day(tmp_path: Path):
    """rollup_day with no data for the date writes zeros gracefully."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"

    r = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    assert r["date"] == date
    assert r["present_seconds"] == 0
    assert r["active_seconds"] == 0
    assert r["sessions"] == 0
    assert r["breaks"] == 0
    assert r["first_sit_ts"] is None
    assert r["last_leave_ts"] is None
    store.close()


def test_rollup_day_does_not_include_next_day(tmp_path: Path):
    """Samples on the next day are not included in today's rollup."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"
    next_date = "2026-06-02"

    base = _ts_on_date(date, hour=23, minute=59)
    _add_present(store, base)  # 23:59 on date — should be counted

    next_base = _ts_on_date(next_date, hour=0, minute=1)
    _add_present(store, next_base)  # 00:01 next day — should NOT be counted

    r = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    assert r["present_seconds"] == 1
    store.close()


# ---------------------------------------------------------------------------
# rollup_day — idempotent upsert
# ---------------------------------------------------------------------------

def test_rollup_day_idempotent_no_duplicate_rows(tmp_path: Path):
    """Running rollup_day twice on the same date produces one row, not two."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"
    base = _ts_on_date(date, hour=9)
    _add_present(store, base)

    store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)
    store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)

    count = store._conn.execute(
        "SELECT COUNT(*) FROM daily_rollups WHERE date = ?", (date,)
    ).fetchone()[0]
    assert count == 1
    store.close()


def test_rollup_day_upsert_overwrites_values(tmp_path: Path):
    """Re-running rollup after adding data updates the row values."""
    store = Store(tmp_path / "t.db")
    date = "2026-06-01"
    base = _ts_on_date(date, hour=9)
    _add_present(store, base)

    r1 = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)
    assert r1["present_seconds"] == 1

    # Add more samples
    for i in range(1, 5):
        _add_present(store, base + i)

    r2 = store.rollup_day(date, work_start_hour=8.5, work_end_hour=17.5)
    assert r2["present_seconds"] == 5

    # Only one row
    count = store._conn.execute(
        "SELECT COUNT(*) FROM daily_rollups WHERE date = ?", (date,)
    ).fetchone()[0]
    assert count == 1
    store.close()


# ---------------------------------------------------------------------------
# recent_rollups
# ---------------------------------------------------------------------------

def test_recent_rollups_empty(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    assert store.recent_rollups(7) == []
    store.close()


def test_recent_rollups_returns_ascending(tmp_path: Path):
    """recent_rollups returns rows ascending by date (oldest first)."""
    store = Store(tmp_path / "t.db")
    for day in ["2026-06-01", "2026-06-02", "2026-06-03"]:
        store.rollup_day(day, work_start_hour=8.5, work_end_hour=17.5)

    result = store.recent_rollups(7)
    dates = [r["date"] for r in result]
    assert dates == sorted(dates)
    store.close()


def test_recent_rollups_limits_to_n(tmp_path: Path):
    """recent_rollups returns at most n_days rows."""
    store = Store(tmp_path / "t.db")
    for i in range(1, 11):
        store.rollup_day(f"2026-06-{i:02d}", work_start_hour=8.5, work_end_hour=17.5)

    result = store.recent_rollups(5)
    assert len(result) == 5
    # Should be the 5 most recent
    dates = [r["date"] for r in result]
    assert max(dates) == "2026-06-10"
    store.close()


# ---------------------------------------------------------------------------
# rollups_between
# ---------------------------------------------------------------------------

def test_rollups_between_range(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    for day in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]:
        store.rollup_day(day, work_start_hour=8.5, work_end_hour=17.5)

    result = store.rollups_between("2026-06-02", "2026-06-04")

    assert len(result) == 3
    dates = [r["date"] for r in result]
    assert "2026-06-02" in dates
    assert "2026-06-03" in dates
    assert "2026-06-04" in dates
    assert "2026-06-01" not in dates
    assert "2026-06-05" not in dates
    store.close()


def test_rollups_between_empty_range(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    store.rollup_day("2026-06-01", work_start_hour=8.5, work_end_hour=17.5)

    result = store.rollups_between("2026-06-10", "2026-06-15")
    assert result == []
    store.close()


def test_rollups_between_ascending_order(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    for day in ["2026-06-03", "2026-06-01", "2026-06-02"]:
        store.rollup_day(day, work_start_hour=8.5, work_end_hour=17.5)

    result = store.rollups_between("2026-06-01", "2026-06-03")
    dates = [r["date"] for r in result]
    assert dates == sorted(dates)
    store.close()


# ---------------------------------------------------------------------------
# earliest_data_date
# ---------------------------------------------------------------------------

def test_earliest_data_date_none_when_empty(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    assert store.earliest_data_date() is None
    store.close()


def test_earliest_data_date_correct(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    ts1 = _ts_on_date("2026-06-01", hour=10)
    ts2 = _ts_on_date("2026-06-05", hour=10)
    _add_present(store, ts1)
    _add_present(store, ts2)

    result = store.earliest_data_date()
    assert result == "2026-06-01"
    store.close()
