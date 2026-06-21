from pathlib import Path

from sentinel.classify import Posture, Status
from sentinel.store import Store


def test_add_and_query_recent(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    store.add_sample(100.0, Status(Posture.GOOD, 5.0, 4.0, 0.0))
    store.add_sample(200.0, Status(Posture.SLOUCHING, 6.0, 18.0, 0.05))
    rows = store.recent(since_ts=150.0)
    assert len(rows) == 1
    assert rows[0]["posture"] == "slouching"
    assert abs(rows[0]["trunk_lean_deg"] - 18.0) < 1e-6
    store.close()


def test_away_sample_records_present_false(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    store.add_sample(100.0, Status(Posture.AWAY, 0.0, 0.0, 0.0))
    rows = store.recent(since_ts=0.0)
    assert rows[0]["present"] == 0
    store.close()
