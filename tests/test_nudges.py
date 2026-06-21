import time

from sentinel.events import Event
from sentinel.nudges import Nudger


def _epoch_at_hm(hour: int, minute: int = 0) -> float:
    """Epoch timestamp at the given local hour:minute on 2026-06-17."""
    return time.mktime((2026, 6, 17, hour, minute, 0, 0, 0, -1))


def _epoch_at_hour(hour: int) -> float:
    """Epoch timestamp at the given local hour on 2026-06-17 (minute=0)."""
    return _epoch_at_hm(hour, 0)


def _nudger(**kw):
    spoken, notified = [], []
    n = Nudger(
        work_start_hour=8.5,
        work_end_hour=17.5,
        cooldown_seconds={"break_due": 600},
        default_cooldown_seconds=300,
        speak_volume=50,
        speak_fn=lambda msg, vol: spoken.append((msg, vol)),
        notify_fn=lambda title, msg: notified.append((title, msg)),
        **kw,
    )
    return n, spoken, notified


def test_fires_inside_active_window():
    n, spoken, notified = _nudger()
    fired = n.dispatch(Event("break_due", 0.0, "stand up"), _epoch_at_hour(10))
    assert fired is True
    assert spoken == [("stand up", 50)]
    assert notified and notified[0][1] == "stand up"


def test_suppressed_outside_active_window():
    n, spoken, notified = _nudger()
    fired = n.dispatch(Event("break_due", 0.0, "stand up"), _epoch_at_hour(20))
    assert fired is False
    assert spoken == [] and notified == []


def test_cooldown_suppresses_repeat():
    n, spoken, _ = _nudger()
    base = _epoch_at_hour(10)
    assert n.dispatch(Event("break_due", 0.0, "m"), base) is True
    assert n.dispatch(Event("break_due", 0.0, "m"), base + 599) is False  # within 600s
    assert n.dispatch(Event("break_due", 0.0, "m"), base + 601) is True   # past cooldown


def test_unknown_type_uses_default_cooldown():
    n, spoken, _ = _nudger()
    base = _epoch_at_hour(10)
    assert n.dispatch(Event("returned", 0.0, "hi"), base) is True
    assert n.dispatch(Event("returned", 0.0, "hi"), base + 299) is False
    assert n.dispatch(Event("returned", 0.0, "hi"), base + 301) is True


def test_empty_message_is_not_dispatched():
    n, spoken, notified = _nudger()
    fired = n.dispatch(Event("left_desk", 0.0, ""), _epoch_at_hour(10))
    assert fired is False
    assert spoken == [] and notified == []


# ------------------------------------------------------------------
# Fractional active-window boundary tests (work_start_hour=8.5)
# ------------------------------------------------------------------

def test_8_29_excluded_from_active_window():
    """8:29 = fractional 8.483... < 8.5 → outside window."""
    n, spoken, _ = _nudger()
    ts = _epoch_at_hm(8, 29)
    fired = n.dispatch(Event("break_due", 0.0, "msg"), ts)
    assert fired is False


def test_8_30_included_in_active_window():
    """8:30 = fractional 8.5 >= 8.5 → inside window."""
    n, spoken, _ = _nudger()
    ts = _epoch_at_hm(8, 30)
    fired = n.dispatch(Event("break_due", 0.0, "msg"), ts)
    assert fired is True


def test_17_29_included_in_active_window():
    """17:29 = fractional 17.483... < 17.5 → still inside window."""
    n, spoken, _ = _nudger()
    ts = _epoch_at_hm(17, 29)
    fired = n.dispatch(Event("break_due", 0.0, "msg"), ts)
    assert fired is True


def test_17_30_excluded_from_active_window():
    """17:30 = fractional 17.5 >= 17.5 → outside window (exclusive end)."""
    n, spoken, _ = _nudger()
    ts = _epoch_at_hm(17, 30)
    fired = n.dispatch(Event("break_due", 0.0, "msg"), ts)
    assert fired is False
