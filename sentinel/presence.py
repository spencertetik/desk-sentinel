from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Session:
    start_ts: float
    end_ts: float


def sessionize(
    samples: list[tuple[float, int]],
    gap_merge_s: float = 20,
    min_session_s: float = 30,
) -> list[Session]:
    """Convert an ordered list of (ts, present) tuples into cleaned sessions.

    Algorithm:
      1. Identify contiguous present=1 runs.
      2. Merge adjacent runs whose gap (time between them) is < gap_merge_s
         - a short glance away does not split a session.
      3. Drop sessions shorter than min_session_s - transient blips are noise.

    The gap measured in step 2 includes both present=0 samples and real
    time gaps with no samples at all (app off).  A trailing-open session
    (last sample is still present=1) is closed at that last sample ts.
    """
    if not samples:
        return []

    # Step 1 - find contiguous present=1 runs as (run_start, run_end) pairs
    runs: list[tuple[float, float]] = []
    run_start: float | None = None
    run_end: float | None = None

    for ts, present in samples:
        if present:
            if run_start is None:
                run_start = ts
            run_end = ts
        else:
            if run_start is not None:
                runs.append((run_start, run_end))
                run_start = None
                run_end = None

    # Handle trailing open session (last sample is present=1)
    if run_start is not None:
        runs.append((run_start, run_end))

    if not runs:
        return []

    # Step 2 - merge runs with small gaps
    merged: list[tuple[float, float]] = [runs[0]]
    for start, end in runs[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end < gap_merge_s:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))

    # Step 3 - drop short sessions
    return [
        Session(start_ts=s, end_ts=e)
        for s, e in merged
        if e - s >= min_session_s
    ]


def summarize_day(sessions: list[Session]) -> dict:
    """Aggregate a list of sessions into a day-level summary dict.

    Returns keys: total_seconds, session_count, first_sit_ts, last_leave_ts.
    All values are 0 / None when the session list is empty.
    """
    if not sessions:
        return {
            "total_seconds": 0.0,
            "session_count": 0,
            "first_sit_ts": None,
            "last_leave_ts": None,
        }

    total = sum(s.end_ts - s.start_ts for s in sessions)
    return {
        "total_seconds": total,
        "session_count": len(sessions),
        "first_sit_ts": sessions[0].start_ts,
        "last_leave_ts": sessions[-1].end_ts,
    }


def tracked_ranges(
    samples: list[tuple[float, int]],
    max_gap_s: float = 5.0,
) -> list[dict]:
    """Return contiguous time windows where any samples exist (app was running).

    Gaps larger than max_gap_s between consecutive samples indicate the app
    was off - those gaps are untracked time.  Each returned range is a dict
    with start_ts and end_ts.
    """
    if not samples:
        return []

    ranges: list[dict] = []
    span_start = samples[0][0]
    span_end = samples[0][0]

    for ts, _ in samples[1:]:
        if ts - span_end > max_gap_s:
            ranges.append({"start_ts": span_start, "end_ts": span_end})
            span_start = ts
        span_end = ts

    ranges.append({"start_ts": span_start, "end_ts": span_end})
    return ranges
