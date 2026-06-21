"""Tests for the active-work column in Store — migration + add_sample + aggregation."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from sentinel.classify import Posture, Status
from sentinel.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_status(posture: Posture = Posture.GOOD, active: bool = False) -> Status:
    import dataclasses
    return dataclasses.replace(Status(posture, 0.0, 0.0, 0.0), active=active)


def _mk_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.db")


# ---------------------------------------------------------------------------
# Migration: old-style DB (no active column) gains the column on init
# ---------------------------------------------------------------------------

_OLD_SCHEMA = """
CREATE TABLE metrics_samples (
    ts REAL NOT NULL,
    forward_head_deg REAL,
    trunk_lean_deg REAL,
    shoulder_drop REAL,
    posture TEXT,
    present INTEGER
);
CREATE INDEX idx_metrics_ts ON metrics_samples(ts);
CREATE TABLE events (ts REAL NOT NULL, type TEXT, message TEXT);
CREATE INDEX idx_events_ts ON events(ts);
"""


def test_migration_adds_active_column_to_existing_db(tmp_path: Path):
    """Store.__init__ adds the 'active' column to a DB that pre-dates it."""
    db_path = tmp_path / "old.db"

    # Create a DB without the active column
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_OLD_SCHEMA)
        conn.execute(
            "INSERT INTO metrics_samples "
            "(ts, forward_head_deg, trunk_lean_deg, shoulder_drop, posture, present) "
            "VALUES (1.0, 0, 0, 0, 'good', 1)"
        )
        conn.commit()

    # Opening with Store should add the column transparently
    store = Store(db_path)
    cols = {
        row[1]
        for row in store._conn.execute("PRAGMA table_info(metrics_samples)").fetchall()
    }
    assert "active" in cols, "migration did not add active column"

    # Existing row should have default 0
    row = store._conn.execute("SELECT active FROM metrics_samples WHERE ts=1.0").fetchone()
    assert row[0] == 0
    store.close()


def test_migration_idempotent_on_fresh_db(tmp_path: Path):
    """Migration on a fresh DB (which already has the column) is a no-op."""
    store1 = Store(tmp_path / "fresh.db")
    store1.close()
    # Re-opening should not error
    store2 = Store(tmp_path / "fresh.db")
    store2.close()


# ---------------------------------------------------------------------------
# add_sample writes the active column correctly
# ---------------------------------------------------------------------------

def test_add_sample_writes_active_true(tmp_path: Path):
    store = _mk_store(tmp_path)
    store.add_sample(10.0, _mk_status(Posture.GOOD, active=True))
    row = store._conn.execute("SELECT active FROM metrics_samples WHERE ts=10.0").fetchone()
    assert row[0] == 1
    store.close()


def test_add_sample_writes_active_false(tmp_path: Path):
    store = _mk_store(tmp_path)
    store.add_sample(10.0, _mk_status(Posture.GOOD, active=False))
    row = store._conn.execute("SELECT active FROM metrics_samples WHERE ts=10.0").fetchone()
    assert row[0] == 0
    store.close()


def test_add_sample_away_writes_active_zero(tmp_path: Path):
    """Away samples always write active=0 (app loop ensures this, store confirms)."""
    store = _mk_store(tmp_path)
    # Even if caller passes active=False for AWAY (which the app loop always does)
    store.add_sample(10.0, _mk_status(Posture.AWAY, active=False))
    row = store._conn.execute(
        "SELECT present, active FROM metrics_samples WHERE ts=10.0"
    ).fetchone()
    assert row[0] == 0  # present
    assert row[1] == 0  # active
    store.close()


# ---------------------------------------------------------------------------
# active_idle_seconds aggregation
# ---------------------------------------------------------------------------

def test_active_idle_seconds_empty(tmp_path: Path):
    store = _mk_store(tmp_path)
    result = store.active_idle_seconds(since_ts=0.0)
    assert result == {"active_seconds": 0, "idle_seconds": 0}
    store.close()


def test_active_idle_seconds_counts_correctly(tmp_path: Path):
    store = _mk_store(tmp_path)
    ts = 1000.0
    # 3 active present, 2 idle present, 2 away (not counted)
    for i in range(3):
        store.add_sample(ts + i, _mk_status(Posture.GOOD, active=True))
    for i in range(2):
        store.add_sample(ts + 10 + i, _mk_status(Posture.GOOD, active=False))
    for i in range(2):
        store.add_sample(ts + 20 + i, _mk_status(Posture.AWAY, active=False))

    result = store.active_idle_seconds(since_ts=ts - 1)
    assert result["active_seconds"] == 3
    assert result["idle_seconds"] == 2
    store.close()


def test_active_idle_seconds_respects_since_ts(tmp_path: Path):
    store = _mk_store(tmp_path)
    store.add_sample(100.0, _mk_status(Posture.GOOD, active=True))
    store.add_sample(200.0, _mk_status(Posture.GOOD, active=True))
    store.add_sample(300.0, _mk_status(Posture.GOOD, active=False))

    result = store.active_idle_seconds(since_ts=150.0)
    assert result["active_seconds"] == 1  # only ts=200
    assert result["idle_seconds"] == 1    # only ts=300
    store.close()


# ---------------------------------------------------------------------------
# presence_by_day gains active_seconds / idle_seconds per day
# ---------------------------------------------------------------------------

def test_presence_by_day_includes_active_idle(tmp_path: Path):
    store = _mk_store(tmp_path)
    import time
    t = time.localtime()
    base = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 10, 0, 0, 0, 0, -1))

    store.add_sample(base,     _mk_status(Posture.GOOD, active=True))
    store.add_sample(base + 1, _mk_status(Posture.GOOD, active=True))
    store.add_sample(base + 2, _mk_status(Posture.GOOD, active=False))
    store.add_sample(base + 3, _mk_status(Posture.AWAY, active=False))  # away, not counted

    result = store.presence_by_day(since_ts=base - 1)
    assert len(result) == 1
    day = result[0]
    assert day["seconds"] == 3           # 2 active + 1 idle (away excluded)
    assert day["active_seconds"] == 2
    assert day["idle_seconds"] == 1
    store.close()


def test_active_idle_seconds_active_share(tmp_path: Path):
    """active_share % = active / (active + idle) * 100"""
    store = _mk_store(tmp_path)
    ts = 500.0
    for i in range(3):
        store.add_sample(ts + i, _mk_status(Posture.GOOD, active=True))
    for i in range(1):
        store.add_sample(ts + 10 + i, _mk_status(Posture.GOOD, active=False))

    ai = store.active_idle_seconds(since_ts=ts - 1)
    total = ai["active_seconds"] + ai["idle_seconds"]
    active_share = round(100.0 * ai["active_seconds"] / total, 1) if total else 0.0
    assert active_share == 75.0
    store.close()
