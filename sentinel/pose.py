from __future__ import annotations

import cv2
import mediapipe as mp

from sentinel.landmarks import Landmark, NUM_LANDMARKS

_mp_pose = mp.solutions.pose


class PoseEstimator:
    def __init__(self, model_complexity: int = 1, min_detection_confidence: float = 0.5):
        self._pose = _mp_pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=0.5,
        )

    def estimate(self, frame_bgr) -> list[Landmark] | None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self._pose.process(rgb)
        if not result.pose_landmarks:
            return None
        lms = result.pose_landmarks.landmark
        out = []
        for i in range(NUM_LANDMARKS):
            lm = lms[i]
            out.append(Landmark(lm.x, lm.y, lm.z, lm.visibility))
        return out

    def close(self) -> None:
        self._pose.close()
