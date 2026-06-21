from pathlib import Path

from sentinel.classify import Posture, Status
from sentinel.events import Event
from sentinel.store import Store


def test_add_and_query_events(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    store.add_event(Event("break_due", 100.0, "stand up"))
    store.add_event(Event("returned", 200.0, "welcome"))
    rows = store.recent_events(since_ts=150.0)
    assert len(rows) == 1
    assert rows[0]["type"] == "returned"
    assert rows[0]["message"] == "welcome"
    store.close()


def test_daily_summary_counts(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    # 3 present samples: 1 good, 2 bad -> slouch_pct ~66.7
    store.add_sample(10.0, Status(Posture.GOOD, 1, 1, 0))
    store.add_sample(11.0, Status(Posture.SLOUCHING, 1, 20, 0))
    store.add_sample(12.0, Status(Posture.FORWARD_HEAD, 40, 1, 0))
    store.add_sample(13.0, Status(Posture.AWAY, 0, 0, 0))  # not present
    store.add_event(Event("break_due", 14.0, "x"))
    s = store.daily_summary(since_ts=0.0)
    assert s["present_samples"] == 3
    assert s["bad_samples"] == 2
    assert abs(s["slouch_pct"] - 66.7) < 0.2
    assert s["breaks"] == 1
    store.close()
