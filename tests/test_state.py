import time

from sentinel.classify import Posture, Status
from sentinel.state import SharedState


def _status():
    return Status(Posture.GOOD, 5.0, 3.0, 0.0)


def test_loop_age_starts_small():
    st = SharedState()
    assert st.loop_age() < 1.0


def test_update_resets_loop_age():
    st = SharedState()
    time.sleep(0.05)
    assert st.loop_age() >= 0.05
    st.update(b"", _status(), True, 1.0)
    # heartbeat just bumped -> age back near zero
    assert st.loop_age() < 0.05


def test_snapshot_reflects_update():
    st = SharedState()
    st.update(b"x", _status(), True, 42.0)
    snap = st.snapshot()
    assert snap["posture"] == "good"
    assert snap["sitting_seconds"] == 42.0
    assert snap["healthy"] is True
