import pytest
from fastapi.testclient import TestClient

from sentinel.classify import Posture, Status
from sentinel.server import create_app
from sentinel.state import SharedState


def _state_with_data():
    state = SharedState()
    state.update(b"\xff\xd8jpegbytes", Status(Posture.GOOD, 5.0, 4.0, 0.0), True, 12.0)
    return state


def test_health_endpoint():
    app = create_app(_state_with_data(), static_dir=None)
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["posture"] == "good"
    assert r.json()["healthy"] is True


def test_stream_returns_multipart():
    app = create_app(_state_with_data(), static_dir=None)
    client = TestClient(app)
    # single-shot frame endpoint for testability
    r = client.get("/frame.jpg")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8jpegbytes"
    assert r.headers["content-type"] == "image/jpeg"


def test_history_endpoint_with_store():
    from sentinel.server import create_app
    from sentinel.state import SharedState
    from fastapi.testclient import TestClient

    class FakeStore:
        def recent_events(self, since_ts):
            return [{"ts": 1.0, "type": "break_due", "message": "stand up"}]
        def daily_summary(self, since_ts):
            return {"present_samples": 10, "bad_samples": 3, "slouch_pct": 30.0, "breaks": 1}

    app = create_app(SharedState(), static_dir=None, store=FakeStore())
    client = TestClient(app)
    r = client.get("/api/history")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["slouch_pct"] == 30.0
    assert body["events"][0]["type"] == "break_due"


def test_history_endpoint_without_store_returns_empty():
    from sentinel.server import create_app
    from sentinel.state import SharedState
    from fastapi.testclient import TestClient

    app = create_app(SharedState(), static_dir=None)
    client = TestClient(app)
    r = client.get("/api/history")
    assert r.status_code == 200
    assert r.json() == {"events": [], "summary": {}}


# ---------------------------------------------------------------------------
# /api/presence
# ---------------------------------------------------------------------------

class _FakeStorePresence:
    """Minimal store stub for presence endpoint tests."""

    def present_samples(self, since_ts):
        # Two present sessions with a gap
        return [
            (1_000.0, 1), (1_001.0, 1), (1_002.0, 1),   # session 1
            (1_060.0, 0),                                   # away
            (1_120.0, 1), (1_121.0, 1),                    # session 2
        ]

    def presence_by_hour_of_day(self, since_ts):
        return {h: 0 for h in range(24)}

    def presence_by_day(self, since_ts):
        return []

    def work_hours_split(self, since_ts, work_start_hour, work_end_hour):
        return {"work_seconds": 0, "off_seconds": 0}

    def active_idle_seconds(self, since_ts):
        return {"active_seconds": 120, "idle_seconds": 30}

    # existing required methods (unused here)
    def recent_events(self, since_ts):
        return []

    def daily_summary(self, since_ts):
        return {}


def test_presence_endpoint_with_store_returns_correct_shape():
    from sentinel.config import PresenceConfig
    from sentinel.server import create_app
    from sentinel.state import SharedState
    from fastapi.testclient import TestClient

    app = create_app(
        SharedState(),
        static_dir=None,
        store=_FakeStorePresence(),
        presence_cfg=PresenceConfig(),
    )
    client = TestClient(app)
    r = client.get("/api/presence")
    assert r.status_code == 200
    body = r.json()

    # top-level keys
    assert set(body.keys()) == {"today", "by_hour", "by_day", "work_split"}

    # today
    today = body["today"]
    assert "date" in today
    assert isinstance(today["total_seconds"], (int, float))
    assert isinstance(today["session_count"], int)
    assert "sessions" in today
    assert "tracked_ranges" in today
    # active-work fields
    assert "active_seconds" in today
    assert "idle_seconds" in today
    assert isinstance(today["active_seconds"], int)
    assert isinstance(today["idle_seconds"], int)

    # by_hour — always 24 entries
    assert len(body["by_hour"]) == 24
    assert body["by_hour"][0]["hour"] == 0
    assert body["by_hour"][23]["hour"] == 23

    # work_split keys
    ws = body["work_split"]
    assert "work_seconds" in ws
    assert "off_seconds" in ws


def test_presence_endpoint_without_store_returns_empty():
    from sentinel.server import create_app
    from sentinel.state import SharedState
    from fastapi.testclient import TestClient

    app = create_app(SharedState(), static_dir=None)
    client = TestClient(app)
    r = client.get("/api/presence")
    assert r.status_code == 200
    body = r.json()

    assert body["today"]["total_seconds"] == 0.0
    assert body["today"]["session_count"] == 0
    assert body["today"]["sessions"] == []
    assert body["today"]["tracked_ranges"] == []
    assert body["today"]["first_sit_ts"] is None
    assert body["today"]["last_leave_ts"] is None
    assert len(body["by_hour"]) == 24
    assert all(e["seconds"] == 0 for e in body["by_hour"])
    assert body["by_day"] == []
    assert body["work_split"] == {"work_seconds": 0, "off_seconds": 0}


def test_presence_endpoint_default_presence_cfg():
    """create_app without presence_cfg uses PresenceConfig() defaults."""
    from sentinel.server import create_app
    from sentinel.state import SharedState
    from fastapi.testclient import TestClient

    app = create_app(SharedState(), static_dir=None, store=_FakeStorePresence())
    client = TestClient(app)
    r = client.get("/api/presence")
    assert r.status_code == 200




def test_presence_endpoint_active_idle_seconds():
    """active_seconds and idle_seconds are forwarded from FakeStore."""
    from sentinel.config import PresenceConfig
    from sentinel.server import create_app
    from sentinel.state import SharedState
    from fastapi.testclient import TestClient

    app = create_app(
        SharedState(),
        static_dir=None,
        store=_FakeStorePresence(),
        presence_cfg=PresenceConfig(),
    )
    client = TestClient(app)
    r = client.get("/api/presence")
    assert r.status_code == 200
    today = r.json()["today"]
    assert today["active_seconds"] == 120
    assert today["idle_seconds"] == 30

    # by_day items from FakeStore return []  — just confirm no crash
    assert r.json()["by_day"] == []


def test_health_endpoint_includes_active():
    """Snapshot from SharedState carries the active flag."""
    from sentinel.classify import Posture, Status
    from sentinel.server import create_app
    from sentinel.state import SharedState
    from fastapi.testclient import TestClient
    import dataclasses

    state = SharedState()
    s = dataclasses.replace(Status(Posture.GOOD, 5.0, 4.0, 0.0), active=True)
    state.update(b"\xff\xd8bytes", s, True, 0.0)
    app = create_app(state, static_dir=None)
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["active"] is True

# ---------------------------------------------------------------------------
# /api/ask — talk-button endpoint
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mute_say(monkeypatch):
    """The /api/ask endpoint speaks answers via macOS `say`; no-op it in tests
    so the suite stays silent and fast."""
    monkeypatch.setattr("sentinel.server.speak_mac", lambda *a, **k: None)


class _FakeStoreAsk:
    """Minimal store stub satisfying gather_stats() requirements."""

    def daily_summary(self, since_ts):
        return {"present_samples": 3600, "breaks": 2, "bad_samples": 10}

    def posture_quality(self, since_ts):
        return {"good_pct": 80.0, "samples": 100}

    def present_samples(self, since_ts):
        return []

    def presence_by_day(self, since_ts):
        return []

    def recent_events(self, since_ts):
        return []


def test_ask_text_path(monkeypatch):
    """JSON question path returns {question, answer}."""
    import sentinel.voice.llm as voice_llm
    from sentinel.config import VoiceConfig

    monkeypatch.setattr(
        voice_llm, "answer",
        lambda question, brief, model, url: "You've been at your desk for 1 hour.",
    )

    app = create_app(
        _state_with_data(), static_dir=None,
        store=_FakeStoreAsk(), voice_cfg=VoiceConfig(),
    )
    client = TestClient(app)
    r = client.post("/api/ask", json={"question": "How long have I been sitting?"})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "How long have I been sitting?"
    assert body["answer"] == "You've been at your desk for 1 hour."


def test_ask_missing_store():
    """503 when store=None."""
    from sentinel.config import VoiceConfig

    app = create_app(
        _state_with_data(), static_dir=None,
        store=None, voice_cfg=VoiceConfig(),
    )
    client = TestClient(app)
    r = client.post("/api/ask", json={"question": "Hello?"})
    assert r.status_code == 503


def test_ask_empty_question(monkeypatch):
    """Empty or blank question returns error JSON, no LLM call."""
    import sentinel.voice.llm as voice_llm
    from sentinel.config import VoiceConfig

    # Should never be reached for blank questions
    monkeypatch.setattr(voice_llm, "answer", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("LLM called on blank question")))

    app = create_app(
        _state_with_data(), static_dir=None,
        store=_FakeStoreAsk(), voice_cfg=VoiceConfig(),
    )
    client = TestClient(app)

    r = client.post("/api/ask", json={"question": ""})
    assert r.status_code == 200
    assert "error" in r.json()

    r = client.post("/api/ask", json={"question": "   "})
    assert r.status_code == 200
    assert "error" in r.json()


def test_ask_audio_path_wiring(monkeypatch):
    """Audio upload path: transcribe_file + llm.answer wiring (no real model)."""
    import sentinel.server as server_mod
    import sentinel.voice.llm as voice_llm
    from sentinel.config import VoiceConfig

    class _FakeTranscriber:
        def transcribe_file(self, path: str) -> str:
            return "How many breaks have I taken?"

    # Pre-populate the singleton so _get_transcriber() returns our fake
    monkeypatch.setattr(server_mod, "_transcriber", _FakeTranscriber())
    monkeypatch.setattr(
        voice_llm, "answer",
        lambda question, brief, model, url: "You've taken 2 breaks.",
    )

    app = create_app(
        _state_with_data(), static_dir=None,
        store=_FakeStoreAsk(), voice_cfg=VoiceConfig(),
    )
    client = TestClient(app)

    fake_audio = b"RIFF\x24\x00\x00\x00WAVEfmt "  # plausible header bytes
    r = client.post(
        "/api/ask",
        files={"audio": ("recording.webm", fake_audio, "audio/webm")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "How many breaks have I taken?"
    assert body["answer"] == "You've taken 2 breaks."


def test_ask_audio_empty_transcript(monkeypatch):
    """Empty transcription from audio returns the 'didn't catch that' error."""
    import sentinel.server as server_mod
    from sentinel.config import VoiceConfig

    class _SilentTranscriber:
        def transcribe_file(self, path: str) -> str:
            return ""  # silence / no speech detected

    monkeypatch.setattr(server_mod, "_transcriber", _SilentTranscriber())

    app = create_app(
        _state_with_data(), static_dir=None,
        store=_FakeStoreAsk(), voice_cfg=VoiceConfig(),
    )
    client = TestClient(app)

    r = client.post(
        "/api/ask",
        files={"audio": ("q.webm", b"bytes", "audio/webm")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "error" in body
    assert "catch" in body["error"].lower()


def test_ask_ollama_error_returns_friendly_message(monkeypatch):
    """RuntimeError from Ollama → JSON error, not 500."""
    import sentinel.voice.llm as voice_llm
    from sentinel.config import VoiceConfig

    def _boom(*a, **kw):
        raise RuntimeError("Ollama unreachable")

    monkeypatch.setattr(voice_llm, "answer", _boom)

    app = create_app(
        _state_with_data(), static_dir=None,
        store=_FakeStoreAsk(), voice_cfg=VoiceConfig(),
    )
    client = TestClient(app)
    r = client.post("/api/ask", json={"question": "How am I doing?"})
    assert r.status_code == 200
    body = r.json()
    assert "error" in body
    assert "brain" in body["error"].lower()
