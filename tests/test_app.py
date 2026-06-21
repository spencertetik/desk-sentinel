from sentinel.app import advance_sit_timer
from sentinel.classify import Posture


def test_away_resets_timer():
    assert advance_sit_timer(100.0, Posture.AWAY, 130.0) == (None, 0.0)


def test_first_presence_starts_timer():
    start, sitting = advance_sit_timer(None, Posture.GOOD, 50.0)
    assert start == 50.0
    assert sitting == 0.0


def test_continued_presence_accumulates():
    start, sitting = advance_sit_timer(50.0, Posture.SLOUCHING, 95.0)
    assert start == 50.0
    assert sitting == 45.0
