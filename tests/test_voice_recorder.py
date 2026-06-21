"""Unit tests for sentinel.voice.recorder.is_trailing_silence (pure VAD)."""
from __future__ import annotations

import pytest

from sentinel.voice.recorder import is_trailing_silence

THRESHOLD = 0.01


# ---------------------------------------------------------------------------
# Basic silence / speech detection
# ---------------------------------------------------------------------------

def test_all_below_threshold_is_silence():
    rms_window = [0.001, 0.002, 0.003, 0.001]
    assert is_trailing_silence(rms_window, THRESHOLD) is True


def test_all_above_threshold_is_not_silence():
    rms_window = [0.05, 0.08, 0.12, 0.07]
    assert is_trailing_silence(rms_window, THRESHOLD) is False


def test_mix_silence_and_speech_is_not_silence():
    """If ANY chunk has speech, trailing silence is False."""
    rms_window = [0.001, 0.002, 0.05, 0.001]
    assert is_trailing_silence(rms_window, THRESHOLD) is False


# ---------------------------------------------------------------------------
# Threshold boundary
# ---------------------------------------------------------------------------

def test_exactly_at_threshold_is_not_silence():
    """A chunk with RMS == threshold is NOT silent (must be strictly below)."""
    rms_window = [0.001, THRESHOLD]
    assert is_trailing_silence(rms_window, THRESHOLD) is False


def test_just_below_threshold_is_silence():
    rms_window = [THRESHOLD - 1e-9]
    assert is_trailing_silence(rms_window, THRESHOLD) is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_window_is_silence():
    """An empty window (no data) counts as silence."""
    assert is_trailing_silence([], THRESHOLD) is True


def test_single_silent_chunk():
    assert is_trailing_silence([0.001], THRESHOLD) is True


def test_single_speech_chunk():
    assert is_trailing_silence([0.5], THRESHOLD) is False


def test_zero_rms_is_silence():
    assert is_trailing_silence([0.0, 0.0, 0.0], THRESHOLD) is True


# ---------------------------------------------------------------------------
# Different thresholds
# ---------------------------------------------------------------------------

def test_high_threshold_treats_speech_as_silence():
    """With a very high threshold, speech-level RMS still counts as silence."""
    rms_window = [0.1, 0.2, 0.15]
    assert is_trailing_silence(rms_window, threshold=0.5) is True


def test_zero_threshold_nothing_is_silence():
    """With threshold=0, only exact-zero is silent; anything positive is not."""
    # Non-zero RMS → not silence
    assert is_trailing_silence([0.001], threshold=0.0) is False


def test_zero_threshold_zero_rms_is_not_silence():
    """RMS must be STRICTLY below threshold; 0.0 < 0.0 is False."""
    assert is_trailing_silence([0.0], threshold=0.0) is False


# ---------------------------------------------------------------------------
# Large windows
# ---------------------------------------------------------------------------

def test_large_silent_window():
    rms_window = [0.001] * 1000
    assert is_trailing_silence(rms_window, THRESHOLD) is True


def test_large_window_one_spike_at_end():
    rms_window = [0.001] * 999 + [0.1]
    assert is_trailing_silence(rms_window, THRESHOLD) is False


def test_large_window_one_spike_at_start():
    """Speech at the start, silence at the tail — still should be silence
    IF the implementation only inspects recent values.  Our implementation
    checks ALL values in rms_window, so one spike anywhere => not silence."""
    rms_window = [0.1] + [0.001] * 999
    # is_trailing_silence checks ALL items in the window, so one early spike
    # returns False — the CALLER controls window length for "trailing" logic.
    assert is_trailing_silence(rms_window, THRESHOLD) is False
