from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from sentinel.classify import Posture, Status
from sentinel.presence import sessionize, summarize_day

# Note: `shoulder_drop` is the spec's `shoulder_slump` (renamed in the plan).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics_samples (
    ts REAL NOT NULL,
    forward_head_deg REAL,
    trunk_lean_deg REAL,
    shoulder_drop REAL,
    posture TEXT,
    present INTEGER,
    active INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics_samples(ts);
CREATE TABLE IF NOT EXISTS events (
    ts REAL NOT NULL,
    type TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS daily_rollups (
    date TEXT PRIMARY KEY,
    present_seconds INTEGER NOT NULL DEFAULT 0,
    active_seconds INTEGER NOT NULL DEFAULT 0,
    idle_seconds INTEGER NOT NULL DEFAULT 0,
    good_seconds INTEGER NOT NULL DEFAULT 0,
    forward_head_seconds INTEGER NOT NULL DEFAULT 0,
    slouching_seconds INTEGER NOT NULL DEFAULT 0,
    sessions INTEGER NOT NULL DEFAULT 0,
    breaks INTEGER NOT NULL DEFAULT 0,
    first_sit_ts REAL,
    last_leave_ts REAL,
    work_seconds INTEGER NOT NULL DEFAULT 0,
    off_seconds INTEGER NOT NULL DEFAULT 0,
    updated_ts REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate(self._conn)
        self._conn.commit()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Schema migration (backward-compatible)
    # ------------------------------------------------------------------

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns/tables introduced after initial schema.  Idempotent."""
        # --- metrics_samples: active column (added in phase 2) ---
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(metrics_samples)").fetchall()
        }
        if "active" not in existing_cols:
            conn.execute(
                "ALTER TABLE metrics_samples ADD COLUMN active INTEGER DEFAULT 0"
            )
            conn.commit()

        # --- daily_rollups table (added in long-term-memory phase) ---
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "daily_rollups" not in existing_tables:
            conn.execute(
                """
                CREATE TABLE daily_rollups (
                    date TEXT PRIMARY KEY,
                    present_seconds INTEGER NOT NULL DEFAULT 0,
                    active_seconds INTEGER NOT NULL DEFAULT 0,
                    idle_seconds INTEGER NOT NULL DEFAULT 0,
                    good_seconds INTEGER NOT NULL DEFAULT 0,
                    forward_head_seconds INTEGER NOT NULL DEFAULT 0,
                    slouching_seconds INTEGER NOT NULL DEFAULT 0,
                    sessions INTEGER NOT NULL DEFAULT 0,
                    breaks INTEGER NOT NULL DEFAULT 0,
                    first_sit_ts REAL,
                    last_leave_ts REAL,
                    work_seconds INTEGER NOT NULL DEFAULT 0,
                    off_seconds INTEGER NOT NULL DEFAULT 0,
                    updated_ts REAL NOT NULL
                )
                """
            )
            conn.commit()

    def add_sample(self, ts: float, status: Status) -> None:
        present = 0 if status.posture is Posture.AWAY else 1
        active = 1 if status.active else 0
        with self._lock:
            self._conn.execute(
                "INSERT INTO metrics_samples "
                "(ts, forward_head_deg, trunk_lean_deg, shoulder_drop, posture, present, active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, status.forward_head_deg, status.trunk_lean_deg,
                 status.shoulder_drop, status.posture.value, present, active),
            )
            self._conn.commit()

    def recent(self, since_ts: float) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM metrics_samples WHERE ts > ? ORDER BY ts ASC",
                (since_ts,),
            )
            return [dict(r) for r in cur.fetchall()]

    def add_event(self, event) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (ts, type, message) VALUES (?, ?, ?)",
                (event.ts, event.type, event.message),
            )
            self._conn.commit()

    def recent_events(self, since_ts: float) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM events WHERE ts > ? ORDER BY ts ASC", (since_ts,)
            )
            return [dict(r) for r in cur.fetchall()]

    def daily_summary(self, since_ts: float) -> dict:
        with self._lock:
            present = self._conn.execute(
                "SELECT COUNT(*) FROM metrics_samples WHERE ts > ? AND present = 1",
                (since_ts,),
            ).fetchone()[0]
            bad = self._conn.execute(
                "SELECT COUNT(*) FROM metrics_samples WHERE ts > ? AND present = 1 "
                "AND posture IN ('slouching', 'forward_head')",
                (since_ts,),
            ).fetchone()[0]
            breaks = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts > ? AND type = 'break_due'",
                (since_ts,),
            ).fetchone()[0]
            slouch_pct = round(100.0 * bad / present, 1) if present else 0.0
            return {
                "present_samples": present,
                "bad_samples": bad,
                "slouch_pct": slouch_pct,
                "breaks": breaks,
            }

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Daily rollup (long-term memory layer)
    # ------------------------------------------------------------------

    def rollup_day(
        self,
        date_str: str,
        work_start_hour: float,
        work_end_hour: float,
    ) -> dict:
        """Aggregate all samples and events for *date_str* (``YYYY-MM-DD``) into
        the ``daily_rollups`` table.  Idempotent — re-running updates the row.

        Args:
            date_str: local date in ``YYYY-MM-DD`` format.
            work_start_hour: fractional work-start hour (e.g. 8.5 = 8:30 AM).
            work_end_hour: fractional work-end hour (e.g. 17.5 = 5:30 PM).

        Returns:
            The rollup dict that was upserted.
        """
        # Compute day boundaries as UTC timestamps via local time
        t = time.strptime(date_str, "%Y-%m-%d")
        day_start = time.mktime(
            (t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)
        )
        day_end = day_start + 86400  # exclusive upper bound

        with self._lock:
            # --- presence / posture counts ---
            cur = self._conn.execute(
                "SELECT posture, active, present FROM metrics_samples "
                "WHERE ts >= ? AND ts < ?",
                (day_start, day_end),
            )
            rows = cur.fetchall()

            present_seconds = 0
            active_seconds = 0
            idle_seconds = 0
            good_seconds = 0
            forward_head_seconds = 0
            slouching_seconds = 0

            for row in rows:
                posture, active, present = row[0], row[1], row[2]
                if present:
                    present_seconds += 1
                    if active:
                        active_seconds += 1
                    else:
                        idle_seconds += 1
                    if posture == "good":
                        good_seconds += 1
                    elif posture == "forward_head":
                        forward_head_seconds += 1
                    elif posture == "slouching":
                        slouching_seconds += 1

            # --- breaks (break_due events) ---
            breaks = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts >= ? AND ts < ? AND type = 'break_due'",
                (day_start, day_end),
            ).fetchone()[0]

            # --- sessions via present_samples + sessionize ---
            samples_cur = self._conn.execute(
                "SELECT ts, present FROM metrics_samples "
                "WHERE ts >= ? AND ts < ? ORDER BY ts ASC",
                (day_start, day_end),
            )
            raw_samples = [(row[0], row[1]) for row in samples_cur.fetchall()]

        # sessionize is pure, no lock needed
        sessions_list = sessionize(raw_samples, gap_merge_s=20, min_session_s=30)
        day_summary = summarize_day(sessions_list)

        # --- work/off split (same fractional-hour logic as work_hours_split) ---
        with self._lock:
            split_cur = self._conn.execute(
                "SELECT "
                "  CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS REAL)"
                "  + CAST(strftime('%M', ts, 'unixepoch', 'localtime') AS REAL) / 60.0"
                "  AS frac_hour, "
                "  COUNT(*) AS cnt "
                "FROM metrics_samples "
                "WHERE ts >= ? AND ts < ? AND present = 1 "
                "GROUP BY CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER), "
                "         CAST(strftime('%M', ts, 'unixepoch', 'localtime') AS INTEGER)",
                (day_start, day_end),
            )
            work_seconds = 0
            off_seconds = 0
            for split_row in split_cur.fetchall():
                frac_hour, cnt = float(split_row[0]), int(split_row[1])
                if work_start_hour <= frac_hour < work_end_hour:
                    work_seconds += cnt
                else:
                    off_seconds += cnt

        updated_ts = time.time()
        rollup = {
            "date": date_str,
            "present_seconds": present_seconds,
            "active_seconds": active_seconds,
            "idle_seconds": idle_seconds,
            "good_seconds": good_seconds,
            "forward_head_seconds": forward_head_seconds,
            "slouching_seconds": slouching_seconds,
            "sessions": day_summary["session_count"],
            "breaks": breaks,
            "first_sit_ts": day_summary["first_sit_ts"],
            "last_leave_ts": day_summary["last_leave_ts"],
            "work_seconds": work_seconds,
            "off_seconds": off_seconds,
            "updated_ts": updated_ts,
        }

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO daily_rollups
                    (date, present_seconds, active_seconds, idle_seconds,
                     good_seconds, forward_head_seconds, slouching_seconds,
                     sessions, breaks, first_sit_ts, last_leave_ts,
                     work_seconds, off_seconds, updated_ts)
                VALUES
                    (:date, :present_seconds, :active_seconds, :idle_seconds,
                     :good_seconds, :forward_head_seconds, :slouching_seconds,
                     :sessions, :breaks, :first_sit_ts, :last_leave_ts,
                     :work_seconds, :off_seconds, :updated_ts)
                ON CONFLICT(date) DO UPDATE SET
                    present_seconds     = excluded.present_seconds,
                    active_seconds      = excluded.active_seconds,
                    idle_seconds        = excluded.idle_seconds,
                    good_seconds        = excluded.good_seconds,
                    forward_head_seconds = excluded.forward_head_seconds,
                    slouching_seconds   = excluded.slouching_seconds,
                    sessions            = excluded.sessions,
                    breaks              = excluded.breaks,
                    first_sit_ts        = excluded.first_sit_ts,
                    last_leave_ts       = excluded.last_leave_ts,
                    work_seconds        = excluded.work_seconds,
                    off_seconds         = excluded.off_seconds,
                    updated_ts          = excluded.updated_ts
                """,
                rollup,
            )
            self._conn.commit()

        return rollup

    def recent_rollups(self, n_days: int) -> list[dict]:
        """Return the most-recent *n_days* rollup rows, ascending by date.

        Returns an empty list when no rollups exist.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM daily_rollups ORDER BY date DESC LIMIT ?",
                (n_days,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        # Return ascending (oldest first)
        return list(reversed(rows))

    def rollups_between(self, start_date: str, end_date: str) -> list[dict]:
        """Return rollup rows where ``start_date <= date <= end_date``, ascending.

        Args:
            start_date: inclusive lower bound, ``YYYY-MM-DD``.
            end_date: inclusive upper bound, ``YYYY-MM-DD``.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM daily_rollups "
                "WHERE date >= ? AND date <= ? ORDER BY date ASC",
                (start_date, end_date),
            )
            return [dict(r) for r in cur.fetchall()]

    def earliest_data_date(self) -> str | None:
        """Return the earliest local date (``YYYY-MM-DD``) that has any samples,
        or None if the table is empty."""
        with self._lock:
            row = self._conn.execute(
                "SELECT strftime('%Y-%m-%d', MIN(ts), 'unixepoch', 'localtime') "
                "FROM metrics_samples"
            ).fetchone()
        return row[0] if row and row[0] else None

    def posture_quality(self, since_ts: float) -> dict:
        """Return posture-good fraction for present=1 samples since ``since_ts``.

        Returns a dict: ``{"good_pct": float, "samples": int}`` where
        ``good_pct`` is the percentage (0.0-100.0) of present samples whose
        posture is 'good'.  ``good_pct`` is 0.0 when there are no samples.
        """
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM metrics_samples "
                "WHERE ts > ? AND present = 1",
                (since_ts,),
            ).fetchone()[0]
            good = self._conn.execute(
                "SELECT COUNT(*) FROM metrics_samples "
                "WHERE ts > ? AND present = 1 AND posture = 'good'",
                (since_ts,),
            ).fetchone()[0]
            good_pct = round(100.0 * good / total, 1) if total else 0.0
            return {"good_pct": good_pct, "samples": total}

    # ------------------------------------------------------------------
    # Presence analytics (read-only, lock-guarded)
    # ------------------------------------------------------------------

    def present_samples(self, since_ts: float) -> list[tuple[float, int]]:
        """Return (ts, present) tuples ordered by ts ascending."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, present FROM metrics_samples "
                "WHERE ts > ? ORDER BY ts ASC",
                (since_ts,),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    def presence_by_hour_of_day(self, since_ts: float) -> dict[int, int]:
        """Return a 24-entry dict mapping local hour (0..23) to present=1 sample count."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS hour, "
                "COUNT(*) AS cnt "
                "FROM metrics_samples "
                "WHERE ts > ? AND present = 1 "
                "GROUP BY hour",
                (since_ts,),
            )
            result: dict[int, int] = {i: 0 for i in range(24)}
            for row in cur.fetchall():
                result[int(row[0])] = int(row[1])
            return result

    def presence_by_day(self, since_ts: float) -> list[dict]:
        """Return per-local-date present=1 totals ordered by date ascending.

        Each entry: {date, seconds, first_ts, last_ts, active_seconds, idle_seconds}.
        active_seconds = present=1 AND active=1; idle_seconds = present=1 AND active=0.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') AS date, "
                "COUNT(*) AS seconds, "
                "MIN(ts) AS first_ts, "
                "MAX(ts) AS last_ts, "
                "SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active_seconds, "
                "SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) AS idle_seconds "
                "FROM metrics_samples "
                "WHERE ts > ? AND present = 1 "
                "GROUP BY date "
                "ORDER BY date ASC",
                (since_ts,),
            )
            return [
                {
                    "date": row[0],
                    "seconds": int(row[1]),
                    "first_ts": float(row[2]),
                    "last_ts": float(row[3]),
                    "active_seconds": int(row[4] or 0),
                    "idle_seconds": int(row[5] or 0),
                }
                for row in cur.fetchall()
            ]

    def active_idle_seconds(self, since_ts: float) -> dict:
        """Return active/idle second counts for present samples since ``since_ts``.

        active_seconds = samples where present=1 AND active=1.
        idle_seconds   = samples where present=1 AND active=0.
        Lock-guarded.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT "
                "SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) "
                "FROM metrics_samples WHERE ts > ? AND present = 1",
                (since_ts,),
            )
            row = cur.fetchone()
            return {
                "active_seconds": int(row[0] or 0),
                "idle_seconds": int(row[1] or 0),
            }

    def work_hours_split(
        self,
        since_ts: float,
        work_start_hour: float,
        work_end_hour: float,
    ) -> dict:
        """Partition present=1 sample count into work vs off-hours.

        work_hours = [work_start_hour, work_end_hour) in local time.
        Supports fractional hours (e.g. 8.5 = 8:30am).
        Returns {work_seconds, off_seconds}.
        """
        with self._lock:
            # Compute fractional local hour per sample, then bucket
            cur = self._conn.execute(
                "SELECT "
                "  CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS REAL)"
                "  + CAST(strftime('%M', ts, 'unixepoch', 'localtime') AS REAL) / 60.0"
                "  AS frac_hour, "
                "  COUNT(*) AS cnt "
                "FROM metrics_samples "
                "WHERE ts > ? AND present = 1 "
                "GROUP BY CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER), "
                "         CAST(strftime('%M', ts, 'unixepoch', 'localtime') AS INTEGER)",
                (since_ts,),
            )
            work_seconds = 0
            off_seconds = 0
            for row in cur.fetchall():
                frac_hour, cnt = float(row[0]), int(row[1])
                if work_start_hour <= frac_hour < work_end_hour:
                    work_seconds += cnt
                else:
                    off_seconds += cnt
            return {"work_seconds": work_seconds, "off_seconds": off_seconds}
