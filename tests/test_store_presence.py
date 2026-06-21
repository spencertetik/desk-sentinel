"""Tests for the presence-analytics read methods on Store."""
from __future__ import annotations

import time
from pathlib import Path

from sentinel.classify import Posture, Status
from sentinel.store import Store


def _slouching(store: Store, ts: float) -> None:
    store.add_sample(ts, Status(Posture.SLOUCHING, 0.0, 0.0, 0.0))


# Helpers ---------------------------------------------------------------

def _ts_at_local_hour(hour: int, minute: int = 0) -> float:
    """Return a float timestamp for today at the given local hour (and optional minute)."""
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hour, minute, 0, 0, 0, -1))


def _today_date() -> str:
    return time.strftime("%Y-%m-%d")


def _present(store: Store, ts: float) -> None:
    store.add_sample(ts, Status(Posture.GOOD, 0.0, 0.0, 0.0))


def _away(store: Store, ts: float) -> None:
    store.add_sample(ts, Status(Posture.AWAY, 0.0, 0.0, 0.0))


# present_samples -------------------------------------------------------

def test_present_samples_returns_all_ordered(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    _present(store, 100.0)
    _away(store, 200.0)
    _present(store, 300.0)

    result = store.present_samples(since_ts=0.0)
    assert len(result) == 3
    assert result[0] == (100.0, 1)
    assert result[1] == (200.0, 0)
    assert result[2] == (300.0, 1)
    store.close()


def test_present_samples_respects_since_ts(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    _present(store, 100.0)
    _present(store, 200.0)
    _present(store, 300.0)

    result = store.present_samples(since_ts=150.0)
    assert len(result) == 2
    assert result[0][0] == 200.0
    store.close()


def test_present_samples_empty(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    assert store.present_samples(since_ts=0.0) == []
    store.close()


# presence_by_hour_of_day -----------------------------------------------

def test_presence_by_hour_always_returns_24_keys(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    result = store.presence_by_hour_of_day(since_ts=0.0)
    assert len(result) == 24
    assert all(result[h] == 0 for h in range(24))
    store.close()


def test_presence_by_hour_counts_correct_bucket(tmp_path: Path):
    store = Store(tmp_path / "t.db")

    ts_10 = _ts_at_local_hour(10)
    ts_15 = _ts_at_local_hour(15)

    # Insert 3 present at 10h, 2 present at 15h, 1 away at 10h (not counted)
    for i in range(3):
        _present(store, ts_10 + i)
    for i in range(2):
        _present(store, ts_15 + i)
    _away(store, ts_10 + 10)

    result = store.presence_by_hour_of_day(since_ts=ts_10 - 1)
    assert result[10] == 3
    assert result[15] == 2
    assert sum(result.values()) == 5
    store.close()


def test_presence_by_hour_since_ts_filters(tmp_path: Path):
    store = Store(tmp_path / "t.db")

    ts_10 = _ts_at_local_hour(10)
    ts_15 = _ts_at_local_hour(15)

    _present(store, ts_10)
    _present(store, ts_15)

    # Filter to exclude the 10h sample
    result = store.presence_by_hour_of_day(since_ts=ts_10 + 1)
    assert result[10] == 0
    assert result[15] == 1
    store.close()


# presence_by_day -------------------------------------------------------

def test_presence_by_day_today(tmp_path: Path):
    store = Store(tmp_path / "t.db")

    ts = _ts_at_local_hour(10)
    for i in range(5):
        _present(store, ts + i)

    result = store.presence_by_day(since_ts=ts - 1)
    assert len(result) == 1
    assert result[0]["date"] == _today_date()
    assert result[0]["seconds"] == 5
    assert result[0]["first_ts"] == ts
    assert result[0]["last_ts"] == ts + 4
    store.close()


def test_presence_by_day_excludes_away(tmp_path: Path):
    store = Store(tmp_path / "t.db")

    ts = _ts_at_local_hour(10)
    _present(store, ts)
    _present(store, ts + 1)
    _away(store, ts + 2)   # should not be counted
    _away(store, ts + 3)

    result = store.presence_by_day(since_ts=ts - 1)
    assert result[0]["seconds"] == 2
    store.close()


def test_presence_by_day_empty(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    assert store.presence_by_day(since_ts=0.0) == []
    store.close()


# work_hours_split ------------------------------------------------------

def test_work_hours_split_basic(tmp_path: Path):
    store = Store(tmp_path / "t.db")

    ts_work = _ts_at_local_hour(10)   # hour 10:00 is in [8.5, 17.5)
    ts_off  = _ts_at_local_hour(18)   # hour 18:00 is outside [8.5, 17.5)

    for i in range(3):
        _present(store, ts_work + i)
    for i in range(2):
        _present(store, ts_off + i)
    _away(store, ts_work + 100)       # away samples not counted

    result = store.work_hours_split(
        since_ts=ts_work - 1,
        work_start_hour=8.5,
        work_end_hour=17.5,
    )
    assert result["work_seconds"] == 3
    assert result["off_seconds"] == 2
    store.close()


def test_work_hours_split_boundary_inclusive_start_exclusive_end(tmp_path: Path):
    store = Store(tmp_path / "t.db")

    ts_8_30  = _ts_at_local_hour(8, 30)   # 8:30 = 8.5 — inclusive start
    ts_17_30 = _ts_at_local_hour(17, 30)  # 17:30 = 17.5 — exclusive end

    _present(store, ts_8_30)
    _present(store, ts_17_30)

    result = store.work_hours_split(
        since_ts=ts_8_30 - 1,
        work_start_hour=8.5,
        work_end_hour=17.5,
    )
    assert result["work_seconds"] == 1   # 8:30 is in [8.5, 17.5)
    assert result["off_seconds"] == 1    # 17:30 is not in [8.5, 17.5)
    store.close()


def test_work_hours_split_fractional_boundary_8_29_is_off(tmp_path: Path):
    """8:29 (fractional 8.483) < 8.5 → off-hours."""
    store = Store(tmp_path / "t.db")

    ts_8_29 = _ts_at_local_hour(8, 29)
    ts_8_30 = _ts_at_local_hour(8, 30)

    _present(store, ts_8_29)
    _present(store, ts_8_30)

    result = store.work_hours_split(
        since_ts=ts_8_29 - 1,
        work_start_hour=8.5,
        work_end_hour=17.5,
    )
    assert result["work_seconds"] == 1   # only 8:30 is work
    assert result["off_seconds"] == 1    # 8:29 is off
    store.close()


def test_work_hours_split_empty(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    result = store.work_hours_split(since_ts=0.0, work_start_hour=8.5, work_end_hour=17.5)
    assert result == {"work_seconds": 0, "off_seconds": 0}
    store.close()


def test_work_hours_split_all_work(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    ts = _ts_at_local_hour(11)
    _present(store, ts)
    _present(store, ts + 1)
    result = store.work_hours_split(
        since_ts=ts - 1, work_start_hour=8.5, work_end_hour=17.5
    )
    assert result["work_seconds"] == 2
    assert result["off_seconds"] == 0
    store.close()


# posture_quality -------------------------------------------------------

def test_posture_quality_mixed(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    ts = 1000.0
    # 3 good present, 1 bad present, 2 away (not counted)
    _present(store, ts)
    _present(store, ts + 1)
    _present(store, ts + 2)
    _slouching(store, ts + 3)
    _away(store, ts + 4)
    _away(store, ts + 5)

    result = store.posture_quality(since_ts=ts - 1)
    assert result["samples"] == 4       # only present=1
    assert result["good_pct"] == 75.0   # 3/4
    store.close()


def test_posture_quality_all_good(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    ts = 1000.0
    for i in range(5):
        _present(store, ts + i)
    result = store.posture_quality(since_ts=ts - 1)
    assert result["good_pct"] == 100.0
    assert result["samples"] == 5
    store.close()


def test_posture_quality_empty(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    result = store.posture_quality(since_ts=0.0)
    assert result["samples"] == 0
    assert result["good_pct"] == 0.0
    store.close()


def test_posture_quality_respects_since_ts(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    ts = 1000.0
    # Two good present samples before cutoff, one bad present after
    _present(store, ts)
    _present(store, ts + 1)
    _slouching(store, ts + 2)

    # since_ts excludes the first two → only the bad sample counts
    result = store.posture_quality(since_ts=ts + 1)  # strictly greater than
    assert result["samples"] == 1
    assert result["good_pct"] == 0.0
    store.close()
