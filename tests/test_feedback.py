"""Tests for sentinel.feedback.compose_status_message (pure, no I/O)."""
from sentinel.feedback import compose_status_message


# ======================================================================
# returned
# ======================================================================

def test_returned_with_hours_and_posture():
    stats = {"desk_minutes": 120, "good_pct": 90.0, "breaks": 2}
    msg = compose_status_message("returned", stats)
    assert "Welcome back" in msg
    assert "2 hours" in msg
    assert "90%" in msg


def test_returned_with_minutes_no_posture():
    stats = {"desk_minutes": 45, "good_pct": None, "breaks": 0}
    msg = compose_status_message("returned", stats)
    assert "Welcome back" in msg
    assert "45 minutes" in msg
    assert "%" not in msg


def test_returned_zero_minutes_no_posture():
    stats = {"desk_minutes": 0, "good_pct": None, "breaks": 0}
    msg = compose_status_message("returned", stats)
    assert "Welcome back" in msg
    assert "a few minutes" in msg


def test_returned_one_minute():
    stats = {"desk_minutes": 1, "good_pct": None, "breaks": 0}
    msg = compose_status_message("returned", stats)
    assert "1 minute" in msg
    assert "minutes" not in msg  # singular


def test_returned_one_hour():
    stats = {"desk_minutes": 60, "good_pct": 100.0, "breaks": 0}
    msg = compose_status_message("returned", stats)
    assert "1 hour" in msg
    assert "hours" not in msg  # singular


def test_returned_posture_rounding():
    """good_pct fractional values round to nearest int."""
    stats = {"desk_minutes": 30, "good_pct": 87.6, "breaks": 0}
    msg = compose_status_message("returned", stats)
    assert "88%" in msg


# ======================================================================
# periodic_checkin
# ======================================================================

def test_checkin_hours_good_posture():
    stats = {"desk_minutes": 90, "good_pct": 85.0, "breaks": 1}
    msg = compose_status_message("periodic_checkin", stats)
    assert "1 hour" in msg         # 90 // 60 = 1
    assert "Posture good" in msg   # 85 >= 80
    assert "1 break so far" in msg


def test_checkin_mixed_posture_zero_breaks():
    stats = {"desk_minutes": 60, "good_pct": 50.0, "breaks": 0}
    msg = compose_status_message("periodic_checkin", stats)
    assert "1 hour" in msg
    assert "Posture mixed" in msg  # 50 < 80
    assert "0 breaks so far" in msg


def test_checkin_no_posture_data():
    stats = {"desk_minutes": 30, "good_pct": None, "breaks": 0}
    msg = compose_status_message("periodic_checkin", stats)
    assert "30 minutes" in msg
    assert "Posture" not in msg    # omitted when no data


def test_checkin_plural_breaks():
    stats = {"desk_minutes": 120, "good_pct": 95.0, "breaks": 3}
    msg = compose_status_message("periodic_checkin", stats)
    assert "3 breaks so far" in msg


def test_checkin_two_hours():
    stats = {"desk_minutes": 120, "good_pct": None, "breaks": 0}
    msg = compose_status_message("periodic_checkin", stats)
    assert "2 hours" in msg


# ======================================================================
# Fallback for unknown kind
# ======================================================================

def test_unknown_kind_fallback():
    stats = {"desk_minutes": 45, "good_pct": None, "breaks": 0}
    msg = compose_status_message("something_else", stats)
    assert "45 minutes" in msg     # still includes time info
