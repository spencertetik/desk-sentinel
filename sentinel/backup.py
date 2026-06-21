"""sentinel/backup.py — SQLite online backup with rotation.

Public API
----------
backup_db(db_path, dest_dir, keep=14) -> str | None
    Copy the live database to dest_dir using SQLite's online backup API (safe
    for concurrent writes).  Returns the path of the written file on success,
    or None if dest_dir's volume is not writable / some other error occurs.
    Never raises.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

log = logging.getLogger("desk_sentinel.backup")


def backup_db(
    db_path: str | Path,
    dest_dir: str | Path,
    keep: int = 14,
) -> str | None:
    """Backup *db_path* to *dest_dir* using the SQLite online backup API.

    Steps:
    1. Verify that dest_dir (or its nearest existing ancestor) is writable; if
       the volume is not mounted / accessible, log and return None.
    2. Create dest_dir if it doesn't exist (only when its parent volume IS
       writable).
    3. Write ``dest_dir/desk_sentinel-YYYY-MM-DD.db`` via
       ``src.backup(dst)``.  This is safe to run concurrently with live writes.
    4. Rotate: keep only the ``keep`` most-recent files (sorted by name,
       which is lexicographic == chronological for ISO-date names).

    Returns the path string of the written backup file, or None on any failure.
    """
    db_path = Path(os.path.expanduser(str(db_path)))
    dest_dir = Path(os.path.expanduser(str(dest_dir)))

    # --- writable-volume check ------------------------------------------------
    # Walk up to the first *existing* ancestor of dest_dir and probe it.
    probe = dest_dir
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            # Reached filesystem root — nothing is mounted
            log.warning("backup: dest_dir volume not available: %s", dest_dir)
            return None
        probe = parent

    if not os.access(str(probe), os.W_OK):
        log.warning("backup: dest_dir not writable: %s (probe: %s)", dest_dir, probe)
        return None

    # --- create dest_dir if needed -------------------------------------------
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("backup: could not create dest_dir %s: %s", dest_dir, exc)
        return None

    # --- write the backup file ------------------------------------------------
    if not db_path.exists():
        log.warning("backup: source DB does not exist: %s", db_path)
        return None

    date_str = time.strftime("%Y-%m-%d", time.localtime())
    dest_file = dest_dir / f"desk_sentinel-{date_str}.db"

    # Online-backup to a LOCAL temp file first, then plain-copy to dest. SQLite's
    # per-page fsync/locking stalls badly on external/exFAT volumes (minutes for
    # a few MB); a local snapshot + a byte copy is ~0.1s and just as consistent.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            tmp_path = tf.name
        src = sqlite3.connect(str(db_path))
        try:
            dst = sqlite3.connect(tmp_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        shutil.copy2(tmp_path, dest_file)
    except Exception as exc:
        log.warning("backup: failed to write %s: %s", dest_file, exc)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    log.info("backup: wrote %s", dest_file)

    # --- rotation: keep the `keep` most-recent files -------------------------
    try:
        existing = sorted(dest_dir.glob("desk_sentinel-*.db"))
        to_delete = existing[: max(0, len(existing) - keep)]
        for old in to_delete:
            try:
                old.unlink()
                log.info("backup: rotated out %s", old)
            except OSError as exc:
                log.warning("backup: could not delete %s: %s", old, exc)
    except Exception as exc:
        log.warning("backup: rotation error: %s", exc)

    return str(dest_file)
