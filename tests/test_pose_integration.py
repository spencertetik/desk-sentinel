from pathlib import Path

import cv2
import pytest

pytestmark = pytest.mark.integration

CLIP = Path(__file__).resolve().parent.parent / "fixtures" / "desk_sample.mp4"


@pytest.mark.skipif(not CLIP.exists(), reason="sample clip not recorded")
def test_pose_on_real_clip_detects_a_person():
    from sentinel.pose import PoseEstimator
    from sentinel.metrics import compute_posture

    cap = cv2.VideoCapture(str(CLIP))
    pose = PoseEstimator()
    present_count = 0
    frames = 0
    while frames < 30:
        ok, frame = cap.read()
        if not ok:
            break
        frames += 1
        lms = pose.estimate(frame)
        if lms and compute_posture(lms, 0.5).present:
            present_count += 1
    cap.release()
    pose.close()
    assert present_count >= 5  # a person is detected in most frames
