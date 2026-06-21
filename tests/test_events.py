from sentinel.classify import Posture, Status
from sentinel.events import EventEngine, Event

# Debounce seconds used in the base _engine() fixture.
_DEB = 4


def _st(posture):
    return Status(posture, 0.0, 0.0, 0.0)


def _engine():
    """Baseline engine used by existing-behaviour tests.

    New Coach-v2 events (posture_slipping, posture_good_streak,
    periodic_checkin) are suppressed via high thresholds so these tests
    remain focused on the specific event they exercise.

    Daily bookend events (morning_arrival, wind_down) are suppressed via
    morning_after_hour=25.0 and work_end_hour=25.0 (unreachable hour values)
    so the bookends never fire on the small epoch values used in these tests.
    """
    return EventEngine(
        break_after_seconds=3600,
        poor_posture_seconds=300,
        debounce_seconds=_DEB,
        posture_slip_seconds=100_000,
        good_streak_seconds=100_000,
        checkin_interval_seconds=100_000,
        morning_after_hour=25.0,
        work_end_hour=25.0,
        wind_down_lead_minutes=0,
    )


def _types(events):
    return [e.type for e in events]


# ======================================================================
# Presence transitions (debounced)
# ======================================================================

def test_returned_on_away_to_present():
    eng = _engine()
    assert _types(eng.update(_st(Posture.AWAY), 0.0)) == []
    assert _types(eng.update(_st(Posture.GOOD), 1.0)) == []   # pending at t=1, not yet 4 s
    assert _types(eng.update(_st(Posture.GOOD), 5.0)) == ["returned"]  # 5-1=4 s sustained


def test_left_desk_on_present_to_away():
    eng = _engine()
    # Commit present first
    eng.update(_st(Posture.GOOD), 0.0)    # pending present at t=0
    eng.update(_st(Posture.GOOD), 4.0)    # "returned" committed
    # Now commit away
    eng.update(_st(Posture.AWAY), 5.0)    # pending away at t=5
    assert _types(eng.update(_st(Posture.AWAY), 9.0)) == ["left_desk"]


def test_break_due_fires_once_after_threshold():
    eng = _engine()
    eng.update(_st(Posture.GOOD), 0.0)          # pending present
    eng.update(_st(Posture.GOOD), 4.0)          # returned; sit_start=4
    assert _types(eng.update(_st(Posture.GOOD), 3603.0)) == []    # 3599 s < 3600
    assert _types(eng.update(_st(Posture.GOOD), 3604.0)) == ["break_due"]  # 3600 s
    assert _types(eng.update(_st(Posture.GOOD), 3700.0)) == []    # not again this session


def test_break_re_arms_after_leaving():
    eng = _engine()
    eng.update(_st(Posture.GOOD), 0.0)          # pending present
    eng.update(_st(Posture.GOOD), 4.0)          # returned; sit_start=4
    eng.update(_st(Posture.GOOD), 3604.0)       # break_due fires (discard result)
    eng.update(_st(Posture.AWAY), 3605.0)       # pending away
    eng.update(_st(Posture.AWAY), 3609.0)       # left_desk; re-arm
    eng.update(_st(Posture.GOOD), 3610.0)       # pending return
    eng.update(_st(Posture.GOOD), 3614.0)       # returned; sit_start=3614
    assert _types(eng.update(_st(Posture.GOOD), 7214.0)) == ["break_due"]  # 3614+3600


def test_poor_posture_sustained_fires_once_then_rearms_on_good():
    eng = _engine()
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)            # returned
    eng.update(_st(Posture.SLOUCHING), 10.0)      # bad_start=10
    assert _types(eng.update(_st(Posture.SLOUCHING), 309.0)) == []     # 299 s < 300
    assert _types(eng.update(_st(Posture.SLOUCHING), 310.0)) == ["poor_posture_sustained"]
    assert _types(eng.update(_st(Posture.SLOUCHING), 700.0)) == []     # not again while bad
    eng.update(_st(Posture.GOOD), 701.0)          # recover → re-arm
    eng.update(_st(Posture.FORWARD_HEAD), 702.0)  # bad starts again at 702
    assert _types(eng.update(_st(Posture.FORWARD_HEAD), 1002.0)) == ["poor_posture_sustained"]


def test_events_carry_ts_and_message():
    eng = _engine()
    eng.update(_st(Posture.AWAY), 0.0)
    eng.update(_st(Posture.GOOD), 1.0)   # pending
    ev = eng.update(_st(Posture.GOOD), 5.0)[0]  # committed; ts=5.0
    assert isinstance(ev, Event)
    assert ev.type == "returned"
    assert ev.ts == 5.0
    assert ev.message   # non-empty base message


# ======================================================================
# Debounce-specific tests
# ======================================================================

def test_debounce_flicker_emits_no_transition():
    """present→away→present within debounce window → no events."""
    eng = _engine()
    eng.update(_st(Posture.GOOD), 0.0)    # pending present at t=0
    # Brief flicker away before 4 s
    eng.update(_st(Posture.AWAY), 1.0)    # raw=away == committed=away: pending cleared
    # Back to present — pending restarts
    assert _types(eng.update(_st(Posture.GOOD), 2.0)) == []


def test_debounce_sustained_change_fires_exactly_once():
    """Sustained for 4 s fires exactly one returned; no duplicate."""
    eng = _engine()
    eng.update(_st(Posture.GOOD), 0.0)
    assert _types(eng.update(_st(Posture.GOOD), 3.9)) == []    # not yet
    assert _types(eng.update(_st(Posture.GOOD), 4.0)) == ["returned"]  # committed
    assert _types(eng.update(_st(Posture.GOOD), 4.1)) == []    # not again


def test_debounce_away_flicker_suppressed():
    """Stand up briefly (< 4 s) while at desk → no left_desk, no spurious returned."""
    eng = _engine()
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)   # returned
    eng.update(_st(Posture.AWAY), 5.0)   # pending away at t=5
    # Come back within 4 s — pending clears, no transition
    assert _types(eng.update(_st(Posture.GOOD), 8.0)) == []


def test_debounce_rapid_flip_collapses_to_nothing():
    """present→away→present all within debounce window → zero transitions."""
    eng = _engine()
    eng.update(_st(Posture.GOOD), 0.0)   # pending present at t=0
    eng.update(_st(Posture.AWAY), 1.0)   # flicker back to away
    eng.update(_st(Posture.GOOD), 2.0)   # pending present restarts at t=2
    eng.update(_st(Posture.AWAY), 2.5)   # flicker again
    # Still no transition — never sustained for 4 s
    assert _types(eng.update(_st(Posture.AWAY), 3.0)) == []


# ======================================================================
# New event: posture_slipping
# ======================================================================

def test_posture_slipping_fires_once_after_slip_window():
    eng = EventEngine(
        break_after_seconds=3600,
        poor_posture_seconds=300,
        debounce_seconds=4,
        posture_slip_seconds=90,
        good_streak_seconds=100_000,
        checkin_interval_seconds=100_000,
        morning_after_hour=25.0, work_end_hour=25.0, wind_down_lead_minutes=0,
    )
    # Commit present
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)          # returned
    # Bad posture starts at t=10
    eng.update(_st(Posture.SLOUCHING), 10.0)
    assert _types(eng.update(_st(Posture.SLOUCHING), 99.0)) == []     # 89 s < 90
    assert _types(eng.update(_st(Posture.SLOUCHING), 100.0)) == ["posture_slipping"]  # 90 s
    assert _types(eng.update(_st(Posture.SLOUCHING), 200.0)) == []    # not again


def test_posture_slipping_rearms_on_recovery():
    eng = EventEngine(
        break_after_seconds=3600,
        poor_posture_seconds=300,
        debounce_seconds=4,
        posture_slip_seconds=90,
        good_streak_seconds=100_000,
        checkin_interval_seconds=100_000,
        morning_after_hour=25.0, work_end_hour=25.0, wind_down_lead_minutes=0,
    )
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)          # returned; bad_start tracks from bad onset
    eng.update(_st(Posture.SLOUCHING), 10.0)    # bad_start=10
    eng.update(_st(Posture.SLOUCHING), 100.0)   # posture_slipping fires (discard)
    # Recover
    eng.update(_st(Posture.GOOD), 150.0)
    # Bad again — new bad_start=160
    eng.update(_st(Posture.FORWARD_HEAD), 160.0)
    assert _types(eng.update(_st(Posture.FORWARD_HEAD), 249.0)) == []     # 89 s < 90
    assert _types(eng.update(_st(Posture.FORWARD_HEAD), 250.0)) == ["posture_slipping"]


# ======================================================================
# New event: posture_good_streak
# ======================================================================

def test_posture_good_streak_fires_after_sustained_good():
    eng = EventEngine(
        break_after_seconds=100_000,
        poor_posture_seconds=100_000,
        debounce_seconds=4,
        posture_slip_seconds=100_000,
        good_streak_seconds=1200,
        checkin_interval_seconds=100_000,
        morning_after_hour=25.0, work_end_hour=25.0, wind_down_lead_minutes=0,
    )
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)     # returned; good_start=4
    assert _types(eng.update(_st(Posture.GOOD), 1203.0)) == []   # 1199 s < 1200
    assert _types(eng.update(_st(Posture.GOOD), 1204.0)) == ["posture_good_streak"]
    assert _types(eng.update(_st(Posture.GOOD), 1300.0)) == []   # not again


def test_posture_good_streak_rearms_on_degradation():
    eng = EventEngine(
        break_after_seconds=100_000,
        poor_posture_seconds=100_000,
        debounce_seconds=4,
        posture_slip_seconds=100_000,
        good_streak_seconds=1200,
        checkin_interval_seconds=100_000,
        morning_after_hour=25.0, work_end_hour=25.0, wind_down_lead_minutes=0,
    )
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)        # returned; good_start=4
    eng.update(_st(Posture.GOOD), 1204.0)     # posture_good_streak fires (discard)
    # Degrade
    eng.update(_st(Posture.SLOUCHING), 1205.0)   # re-arm
    # Good again — new good_start=1210
    eng.update(_st(Posture.GOOD), 1210.0)
    assert _types(eng.update(_st(Posture.GOOD), 2409.0)) == []   # 1199 s < 1200
    assert _types(eng.update(_st(Posture.GOOD), 2410.0)) == ["posture_good_streak"]


# ======================================================================
# New event: periodic_checkin
# ======================================================================

def test_periodic_checkin_fires_on_interval():
    eng = EventEngine(
        break_after_seconds=100_000,
        poor_posture_seconds=100_000,
        debounce_seconds=4,
        posture_slip_seconds=100_000,
        good_streak_seconds=100_000,
        checkin_interval_seconds=3600,
        morning_after_hour=25.0, work_end_hour=25.0, wind_down_lead_minutes=0,
    )
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)      # returned; last_checkin=4
    assert _types(eng.update(_st(Posture.GOOD), 3603.0)) == []   # 3599 s < 3600
    assert _types(eng.update(_st(Posture.GOOD), 3604.0)) == ["periodic_checkin"]
    # Second checkin 3600 s after first
    assert _types(eng.update(_st(Posture.GOOD), 7204.0)) == ["periodic_checkin"]


def test_periodic_checkin_resets_on_leave():
    eng = EventEngine(
        break_after_seconds=100_000,
        poor_posture_seconds=100_000,
        debounce_seconds=4,
        posture_slip_seconds=100_000,
        good_streak_seconds=100_000,
        checkin_interval_seconds=3600,
        morning_after_hour=25.0, work_end_hour=25.0, wind_down_lead_minutes=0,
    )
    eng.update(_st(Posture.GOOD), 0.0)
    eng.update(_st(Posture.GOOD), 4.0)      # returned; last_checkin=4
    eng.update(_st(Posture.GOOD), 3604.0)   # checkin fires (discard)
    # Leave
    eng.update(_st(Posture.AWAY), 3605.0)
    eng.update(_st(Posture.AWAY), 3609.0)   # left_desk; last_checkin=None
    # Return — last_checkin resets to 3614
    eng.update(_st(Posture.GOOD), 3610.0)
    eng.update(_st(Posture.GOOD), 3614.0)   # returned; last_checkin=3614
    # Next checkin at 3614+3600=7214 (not before)
    assert _types(eng.update(_st(Posture.GOOD), 7213.0)) == []
    assert _types(eng.update(_st(Posture.GOOD), 7214.0)) == ["periodic_checkin"]
