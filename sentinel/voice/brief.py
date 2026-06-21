"""voice/brief.py — build a text stats brief for the LLM context window.

The public API is split into two functions so the text-assembly step is
fully pure and unit-testable without a database:

  stats = gather_stats(store, now)      # hits the DB
  text  = build_brief(stats, now)       # pure string formatting
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sentinel.presence import sessionize, summarize_day


# ---------------------------------------------------------------------------
# Data gathering (touches the store — NOT tested as a unit)
# ---------------------------------------------------------------------------

def gather_stats(store: Any, now: float) -> dict:
    """Query the store and return a plain dict of all stats needed for the brief."""
    # Midnight at the start of today (local time)
    lt = time.localtime(now)
    today_start = time.mktime(
        (lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)
    )
    seven_days_ago = now - 7 * 86400

    daily = store.daily_summary(today_start)
    posture_q = store.posture_quality(today_start)

    # Sessionize to get session count + first-sit / last-leave
    today_raw = store.present_samples(today_start)
    sessions = sessionize(today_raw, gap_merge_s=20, min_session_s=30)
    day_summary = summarize_day(sessions)

    # Per-day totals for the recent week
    by_day = store.presence_by_day(seven_days_ago)

    # Recent events (last 24 h)
    recent_events = store.recent_events(now - 86400)

    # Long-term rollups (last 30 days for averages; last 7 for per-day history)
    rollups_30: list[dict] = []
    try:
        rollups_30 = store.recent_rollups(30)
    except Exception:
        rollups_30 = []

    return {
        # today
        "today_present_seconds": daily["present_samples"],
        "today_breaks": daily["breaks"],
        "today_bad_samples": daily["bad_samples"],
        "today_bad_pct": round(100.0 - posture_q["good_pct"], 1),
        "today_good_pct": posture_q["good_pct"],
        "today_posture_samples": posture_q["samples"],
        "today_session_count": day_summary["session_count"],
        "today_first_sit_ts": day_summary["first_sit_ts"],
        "today_last_leave_ts": day_summary["last_leave_ts"],
        # week
        "recent_days": by_day,
        # events
        "recent_events": recent_events,
        # long-term rollups
        "rollups_30": rollups_30,
        # optional live state (populated by agent if SharedState is available)
        "current_posture": None,
        "current_sitting_seconds": None,
        "current_present": None,
    }


# ---------------------------------------------------------------------------
# Pure text assembly (unit-tested)
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: float) -> str:
    """Format a duration in seconds as 'Xh Ym' or 'Xm'."""
    seconds = int(seconds)
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _fmt_time(ts: float | None) -> str:
    if ts is None:
        return "unknown"
    return datetime.fromtimestamp(ts).strftime("%-I:%M %p")


def build_brief(store_stats: dict, now: float) -> str:
    """Assemble a concise text brief from pre-gathered stats.

    This function is PURE — it only reads from ``store_stats`` and ``now``
    and performs no I/O.  It is the target of unit tests.

    Args:
        store_stats: output of :func:`gather_stats` (or a compatible dict for
            testing).
        now: current epoch timestamp.

    Returns:
        A multi-line string suitable for stuffing into the LLM system prompt.
    """
    s = store_stats
    now_dt = datetime.fromtimestamp(now)
    lines: list[str] = [
        f"=== Desk Sentinel Stats Brief — {now_dt.strftime('%Y-%m-%d %H:%M')} ===",
        "",
        "TODAY (so far):",
    ]

    present_s = s.get("today_present_seconds", 0) or 0
    if present_s:
        lines.append(f"  Desk time: {_fmt_duration(present_s)}")
    else:
        lines.append("  Desk time: none recorded yet")

    session_count = s.get("today_session_count", 0) or 0
    if session_count:
        lines.append(f"  Sessions: {session_count}")
        first_sit = _fmt_time(s.get("today_first_sit_ts"))
        last_leave = _fmt_time(s.get("today_last_leave_ts"))
        lines.append(f"  First sat: {first_sit}  |  Last left: {last_leave}")
    else:
        lines.append("  Sessions: none yet")

    good_pct = s.get("today_good_pct", 0.0) or 0.0
    bad_pct = s.get("today_bad_pct", 0.0) or 0.0
    posture_samples = s.get("today_posture_samples", 0) or 0
    if posture_samples:
        lines.append(f"  Posture: {good_pct}% good, {bad_pct}% poor (forward-head or slouch)")
    else:
        lines.append("  Posture: no data yet")

    breaks = s.get("today_breaks", 0) or 0
    lines.append(f"  Breaks taken: {breaks}")

    # Current live state (optional)
    current_posture = s.get("current_posture")
    current_sitting_s = s.get("current_sitting_seconds")
    current_present = s.get("current_present")

    lines.append("")
    lines.append("CURRENT STATE:")
    if current_present is not None:
        if current_present:
            posture_str = current_posture or "unknown posture"
            if current_sitting_s is not None:
                lines.append(
                    f"  At desk — posture: {posture_str}, "
                    f"sitting {_fmt_duration(current_sitting_s)}"
                )
            else:
                lines.append(f"  At desk — posture: {posture_str}")
        else:
            lines.append("  Away from desk")
    else:
        lines.append("  Live state unavailable (tracker not running)")

    # Recent days summary
    recent_days = s.get("recent_days") or []
    if recent_days:
        lines.append("")
        lines.append("RECENT DAYS (desk time per day):")
        for day in recent_days[-7:]:
            lines.append(
                f"  {day['date']}: {_fmt_duration(day['seconds'])}"
            )

    # Long-term rollup history
    rollups_30: list[dict] = s.get("rollups_30") or []
    if rollups_30:
        # Last 7 days per-day detail (most recent 7 rollup rows)
        last_7 = rollups_30[-7:]
        lines.append("")
        lines.append("RECENT HISTORY — last 7 days (from daily rollups):")
        for r in last_7:
            desk_h = r.get("present_seconds", 0) / 3600.0
            present_s = r.get("present_seconds", 0)
            good_s = r.get("good_seconds", 0)
            posture_good_pct = (
                round(100.0 * good_s / present_s, 1) if present_s else 0.0
            )
            lines.append(
                f"  {r['date']}: desk {_fmt_duration(r.get('present_seconds', 0))}"
                f"  posture-good {posture_good_pct}%"
            )

        # 30-day averages
        n = len(rollups_30)
        avg_desk_h = sum(r.get("present_seconds", 0) for r in rollups_30) / (n * 3600.0)
        total_present = sum(r.get("present_seconds", 0) for r in rollups_30)
        total_good = sum(r.get("good_seconds", 0) for r in rollups_30)
        total_active = sum(r.get("active_seconds", 0) for r in rollups_30)
        avg_posture_good_pct = (
            round(100.0 * total_good / total_present, 1) if total_present else 0.0
        )
        avg_active_pct = (
            round(100.0 * total_active / total_present, 1) if total_present else 0.0
        )
        lines.append("")
        lines.append(f"30-DAY AVERAGES ({n} days of data):")
        lines.append(f"  Avg desk time/day: {avg_desk_h:.1f}h")
        lines.append(f"  Avg posture-good:  {avg_posture_good_pct}%")
        lines.append(f"  Avg active:        {avg_active_pct}%")

    return "\n".join(lines)
