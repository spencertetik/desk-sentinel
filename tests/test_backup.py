"""Tests for sentinel.backup.backup_db."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from sentinel.backup import backup_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_db(path: Path, row_count: int = 5) -> None:
    """Create a minimal SQLite DB with a table and some rows."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, val TEXT)")
    for i in range(row_count):
        conn.execute("INSERT INTO test_data (val) VALUES (?)", (f"row{i}",))
    conn.commit()
    conn.close()


def _count_rows(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    n = conn.execute("SELECT COUNT(*) FROM test_data").fetchone()[0]
    conn.close()
    return n


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_backup_creates_file(tmp_path: Path):
    """backup_db writes a .db file in dest_dir."""
    src = tmp_path / "source.db"
    dest_dir = tmp_path / "backups"
    _seed_db(src)

    result = backup_db(src, dest_dir)

    assert result is not None
    assert Path(result).exists()
    assert dest_dir.exists()


def test_backup_file_is_valid_sqlite(tmp_path: Path):
    """The backup file opens as a valid SQLite DB with the same row count."""
    src = tmp_path / "source.db"
    dest_dir = tmp_path / "backups"
    _seed_db(src, row_count=7)

    result = backup_db(src, dest_dir)

    assert result is not None
    assert _count_rows(Path(result)) == 7


def test_backup_filename_contains_date(tmp_path: Path):
    """Backup file name includes today's YYYY-MM-DD."""
    src = tmp_path / "source.db"
    dest_dir = tmp_path / "backups"
    _seed_db(src)

    today = time.strftime("%Y-%m-%d")
    result = backup_db(src, dest_dir)

    assert result is not None
    assert today in Path(result).name


def test_backup_rotation_keeps_keep(tmp_path: Path):
    """After writing N+1 backups, only `keep` files remain."""
    src = tmp_path / "source.db"
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    _seed_db(src)

    keep = 3
    # Pre-seed `keep` old backup files with earlier date names
    for i in range(keep):
        old = dest_dir / f"desk_sentinel-2020-01-0{i+1}.db"
        _seed_db(old, row_count=1)

    # Now run a real backup — this becomes the (keep+1)-th file
    result = backup_db(src, dest_dir, keep=keep)

    assert result is not None
    remaining = sorted(dest_dir.glob("desk_sentinel-*.db"))
    assert len(remaining) == keep
    # The oldest files should have been deleted; the newest kept
    names = [f.name for f in remaining]
    # The real backup (today's date) should be among them
    today = time.strftime("%Y-%m-%d")
    assert any(today in n for n in names)


def test_backup_unwritable_dest_returns_none(tmp_path: Path):
    """A bogus/unwritable dest_dir returns None and does not raise."""
    src = tmp_path / "source.db"
    _seed_db(src)

    # Use a path whose root volume doesn't exist
    bogus_dest = Path("/nonexistent_volume_abc123/backups")

    result = backup_db(src, bogus_dest)

    assert result is None


def test_backup_missing_src_returns_none(tmp_path: Path):
    """If the source DB doesn't exist, returns None without raising."""
    src = tmp_path / "does_not_exist.db"
    dest_dir = tmp_path / "backups"

    result = backup_db(src, dest_dir)

    assert result is None


def test_backup_idempotent_same_day(tmp_path: Path):
    """Running backup twice on the same day overwrites today's file, count stays ≤ keep."""
    src = tmp_path / "source.db"
    dest_dir = tmp_path / "backups"
    _seed_db(src, row_count=3)

    keep = 5
    result1 = backup_db(src, dest_dir, keep=keep)
    result2 = backup_db(src, dest_dir, keep=keep)

    # Both succeed and resolve to the same (or same-dated) filename
    assert result1 is not None
    assert result2 is not None
    remaining = list(dest_dir.glob("desk_sentinel-*.db"))
    assert len(remaining) <= keep
