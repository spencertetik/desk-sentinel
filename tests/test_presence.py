"""Tests for sentinel.presence — pure sessionizer and day summarizer."""
from __future__ import annotations

import pytest
from sentinel.presence import Session, sessionize, summarize_day, tracked_ranges


# ---------------------------------------------------------------------------
# sessionize
# ---------------------------------------------------------------------------

def test_empty_input_returns_empty():
    assert sessionize([]) == []


def test_all_away_returns_empty():
    samples = [(float(i), 0) for i in range(60)]
    assert sessionize(samples) == []


def test_single_continuous_session():
    # 60 consecutive present=1 samples → one session from 0 to 59
    samples = [(float(i), 1) for i in range(60)]
    result = sessionize(samples)
    assert len(result) == 1
    assert result[0].start_ts == 0.0
    assert result[0].end_ts == 59.0


def test_gap_below_threshold_merges():
    # 60s present, 10s away, 60s present → gap=10 < 20 → single merged session
    samples = [(float(i), 1) for i in range(60)]
    samples += [(float(i), 0) for i in range(60, 70)]
    samples += [(float(i), 1) for i in range(70, 130)]
    result = sessionize(samples, gap_merge_s=20, min_session_s=30)
    assert len(result) == 1
    assert result[0].start_ts == 0.0
    assert result[0].end_ts == 129.0


def test_gap_at_threshold_does_not_merge():
    # gap=20 is NOT strictly less than gap_merge_s=20 → two sessions
    samples = [(float(i), 1) for i in range(60)]
    samples += [(float(i), 0) for i in range(60, 80)]   # gap = 80-59 = 21 (first present at 80)
    samples += [(float(i), 1) for i in range(80, 140)]
    result = sessionize(samples, gap_merge_s=20, min_session_s=30)
    # gap between run_end=59 and next run_start=80 is 21 ≥ 20 → no merge
    assert len(result) == 2


def test_gap_above_threshold_does_not_merge():
    # 60s present, 30s away, 60s present → gap=30 ≥ 20 → two sessions
    samples = [(float(i), 1) for i in range(60)]
    samples += [(float(i), 0) for i in range(60, 90)]
    samples += [(float(i), 1) for i in range(90, 150)]
    result = sessionize(samples, gap_merge_s=20, min_session_s=30)
    assert len(result) == 2
    assert result[0].start_ts == 0.0
    assert result[0].end_ts == 59.0
    assert result[1].start_ts == 90.0
    assert result[1].end_ts == 149.0


def test_sub_min_blip_dropped():
    # 10 present samples → duration = 9s < 30 → dropped
    samples = [(float(i), 1) for i in range(10)]
    result = sessionize(samples, min_session_s=30)
    assert result == []


def test_blip_between_long_sessions_is_merged():
    # long session, tiny away, long session: the away is < gap_merge_s so they merge
    samples = [(float(i), 1) for i in range(100)]
    samples += [(100.0, 0)]   # 1 away sample — gap = 1 < 20
    samples += [(float(i), 1) for i in range(101, 200)]
    result = sessionize(samples, gap_merge_s=20, min_session_s=30)
    assert len(result) == 1


def test_trailing_open_session_closed_at_last_ts():
    # Last sample is present=1 → session ends there
    samples = [(float(i), 1) for i in range(60)]
    result = sessionize(samples)
    assert len(result) == 1
    assert result[0].end_ts == 59.0


def test_real_time_gap_merges_when_small():
    # Two present runs separated by a time gap with NO samples (app briefly off)
    # The "gap" for merge purposes is measured as next_run_start - prev_run_end
    # Here: run1 ends at ts=59, run2 starts at ts=75 → gap = 16 < 20 → merge
    samples = [(float(i), 1) for i in range(60)]           # 0..59
    samples += [(float(i), 1) for i in range(75, 135)]     # 75..134 (no samples 60..74)
    result = sessionize(samples, gap_merge_s=20, min_session_s=30)
    assert len(result) == 1
    assert result[0].start_ts == 0.0
    assert result[0].end_ts == 134.0


def test_single_sample_session_below_min_dropped():
    samples = [(1.0, 1)]
    assert sessionize(samples, min_session_s=30) == []


def test_session_exactly_at_min_kept():
    # 30 samples from 0..29 → duration = 29s, which is < 30 → dropped
    # 31 samples from 0..30 → duration = 30s ≥ 30 → kept
    samples_30 = [(float(i), 1) for i in range(31)]   # duration = 30
    result = sessionize(samples_30, min_session_s=30)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# summarize_day
# ---------------------------------------------------------------------------

def test_summarize_empty_sessions():
    result = summarize_day([])
    assert result["total_seconds"] == 0.0
    assert result["session_count"] == 0
    assert result["first_sit_ts"] is None
    assert result["last_leave_ts"] is None


def test_summarize_single_session():
    sessions = [Session(0.0, 3600.0)]
    result = summarize_day(sessions)
    assert result["total_seconds"] == 3600.0
    assert result["session_count"] == 1
    assert result["first_sit_ts"] == 0.0
    assert result["last_leave_ts"] == 3600.0


def test_summarize_multiple_sessions():
    sessions = [Session(0.0, 3600.0), Session(7200.0, 9000.0)]
    result = summarize_day(sessions)
    assert result["total_seconds"] == 3600.0 + 1800.0
    assert result["session_count"] == 2
    assert result["first_sit_ts"] == 0.0
    assert result["last_leave_ts"] == 9000.0


# ---------------------------------------------------------------------------
# tracked_ranges
# ---------------------------------------------------------------------------

def test_tracked_ranges_empty():
    assert tracked_ranges([]) == []


def test_tracked_ranges_single_span():
    samples = [(float(i), 1) for i in range(5)]
    result = tracked_ranges(samples, max_gap_s=5.0)
    assert len(result) == 1
    assert result[0]["start_ts"] == 0.0
    assert result[0]["end_ts"] == 4.0


def test_tracked_ranges_split_on_large_gap():
    # Samples at 0-4, then jump to 100-104 (gap > 5)
    samples = [(float(i), 1) for i in range(5)]
    samples += [(float(i), 0) for i in range(100, 105)]
    result = tracked_ranges(samples, max_gap_s=5.0)
    assert len(result) == 2
    assert result[0]["start_ts"] == 0.0
    assert result[0]["end_ts"] == 4.0
    assert result[1]["start_ts"] == 100.0
    assert result[1]["end_ts"] == 104.0
