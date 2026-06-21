import os
import time

import pytest

pytestmark = pytest.mark.integration

# Point this at your own camera to run the integration test:
#   DESK_SENTINEL_RTSP_URL="rtsp://user:pass@192.168.1.50:554/stream" pytest -m integration
URL = os.environ.get("DESK_SENTINEL_RTSP_URL")


@pytest.mark.skipif(not URL, reason="set DESK_SENTINEL_RTSP_URL to run")
def test_capture_drains_at_stream_rate():
    """The reader must consume the RTSP stream at ~native rate so the decode
    buffer never backs up (which is what causes accumulating display latency).
    The substream is 30fps; require >20fps consumption to prove draining."""
    from sentinel.capture import RtspCapture

    cap = RtspCapture(URL, target_fps=8).start()
    time.sleep(1.0)  # connect + warm up
    start = cap.frames_read()
    time.sleep(3.0)
    read = cap.frames_read() - start
    cap.stop()
    fps = read / 3.0
    assert fps > 20, f"capture only drained {fps:.1f} fps (buffer backs up -> latency)"
