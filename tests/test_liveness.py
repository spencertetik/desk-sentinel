from sentinel.liveness import PresenceLiveness


def test_frozen_pose_is_not_alive():
    """An empty-chair phantom: same position every frame -> never alive."""
    lv = PresenceLiveness(window_s=120, move_delta=0.06)
    alive = True
    t = 0.0
    for _ in range(200):
        # tiny sensor jitter, well under move_delta
        alive = lv.update(True, 0.47 + (t % 2) * 0.005, 0.86, t)
        t += 1.0
    assert alive is False


def test_moving_pose_becomes_alive():
    """A real person drifting across the frame clears the movement threshold."""
    lv = PresenceLiveness(window_s=120, move_delta=0.06)
    alive = False
    for i in range(30):
        alive = lv.update(True, 0.50 + i * 0.01, 0.56, float(i))
    assert alive is True


def test_absent_resets_and_returns_false():
    lv = PresenceLiveness()
    for i in range(10):
        lv.update(True, 0.5 + i * 0.02, 0.56, float(i))
    assert lv.update(False, 0.0, 0.0, 11.0) is False


def test_teleport_to_frozen_phantom_is_rejected():
    """Person moving (alive), then leaves and detector jumps to a frozen chair:
    the chair must NOT inherit the person's liveness."""
    lv = PresenceLiveness(window_s=120, move_delta=0.06, teleport=0.15)
    # real person moving around x~0.7
    a = False
    for i in range(20):
        a = lv.update(True, 0.70 + (i % 5) * 0.02, 0.56, float(i))
    assert a is True
    # detector jumps to the empty chair at 0.47/0.86 and freezes there
    t = 20.0
    last = True
    for _ in range(200):
        last = lv.update(True, 0.47, 0.86, t)
        t += 1.0
    assert last is False


def test_returning_person_proves_liveness_again():
    lv = PresenceLiveness(window_s=120, move_delta=0.06, teleport=0.15)
    # frozen phantom
    for t in range(60):
        assert lv.update(True, 0.47, 0.86, float(t)) is False
    # person returns (teleport) and starts moving
    alive = False
    for i in range(30):
        alive = lv.update(True, 0.70 + i * 0.01, 0.56, 60.0 + i)
    assert alive is True
