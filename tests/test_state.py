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


def test_mute_defaults_off():
    st = SharedState()
    assert st.is_muted() is False
    assert st.snapshot()["muted"] is False


def test_set_and_clear_mute_is_a_toggle():
    st = SharedState()
    st.set_mute()
    assert st.is_muted() is True
    assert st.snapshot()["muted"] is True
    st.clear_mute()
    assert st.is_muted() is False
    assert st.snapshot()["muted"] is False


def test_mute_persists_across_restart(tmp_path):
    path = str(tmp_path / "mute_state.json")
    st = SharedState(mute_state_path=path)
    st.set_mute()
    # A fresh instance (simulating an app restart) reads the persisted state.
    st2 = SharedState(mute_state_path=path)
    assert st2.is_muted() is True
    st2.clear_mute()
    assert SharedState(mute_state_path=path).is_muted() is False


def test_corrupt_mute_file_defaults_unmuted(tmp_path):
    path = tmp_path / "mute_state.json"
    path.write_text("not json{{{")
    assert SharedState(mute_state_path=str(path)).is_muted() is False
