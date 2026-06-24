from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from sentinel.config import PresenceConfig, VoiceConfig
from sentinel.nudges import speak_mac  # reuse the coach's macOS `say` voice
from sentinel.state import SharedState
from sentinel.voice.brief import build_brief, gather_stats
import sentinel.voice.llm as voice_llm

log = logging.getLogger("desk_sentinel.server")

_BOUNDARY = "frame"

# Module-level Transcriber singleton — loaded lazily on first /api/ask request.
_transcriber = None


def _get_transcriber(model_size: str):
    """Return the module-level Transcriber, creating it on first call."""
    global _transcriber
    if _transcriber is None:
        from sentinel.voice.stt import Transcriber
        log.info("Lazy-loading Whisper model %r for /api/ask …", model_size)
        _transcriber = Transcriber(model_size)
    return _transcriber


_NEWS_KEYWORDS = ("news", "headline", "headlines", "happening", "going on")


def _answer_pipeline(question: str, store, voice_cfg, now: float) -> str:
    """Blocking: build the stats brief (+ live AI headlines if the question is
    news-y), then ask the LLM. Runs in a worker thread so the server event loop
    (camera stream + WebSocket) is never blocked."""
    stats = gather_stats(store, now)
    brief = build_brief(stats, now)
    if any(k in question.lower() for k in _NEWS_KEYWORDS):
        try:
            from sentinel.briefing import fetch_ai_headlines
            heads = fetch_ai_headlines("artificial intelligence", 3, timeout=4.0)
            if heads:
                brief += "\n\nLatest AI news headlines:\n" + "\n".join(f"- {h}" for h in heads)
        except Exception as exc:  # noqa: BLE001 — news is best-effort
            log.warning("news fetch for /api/ask failed: %s", exc)
    return voice_llm.answer(
        question, brief, model=voice_cfg.ollama_model, url=voice_cfg.ollama_url
    )


def create_app(
    state: SharedState,
    static_dir: str | None,
    store=None,
    presence_cfg: PresenceConfig | None = None,
    voice_cfg: VoiceConfig | None = None,
) -> FastAPI:
    if presence_cfg is None:
        presence_cfg = PresenceConfig()
    if voice_cfg is None:
        voice_cfg = VoiceConfig()

    app = FastAPI(title="Desk Sentinel")

    @app.get("/api/health")
    def health():
        return state.snapshot()

    @app.post("/api/mute")
    def mute():
        """Silence spoken nudges + notifications until explicitly unmuted."""
        state.set_mute()
        log.info("nudges muted via dashboard")
        return state.snapshot()

    @app.post("/api/unmute")
    def unmute():
        state.clear_mute()
        log.info("nudges unmuted via dashboard")
        return state.snapshot()

    @app.get("/frame.jpg")
    def frame():
        jpeg = state.jpeg()
        if jpeg is None:
            return Response(status_code=503)
        return Response(content=jpeg, media_type="image/jpeg")

    @app.get("/stream.mjpg")
    def stream():
        def gen():
            while True:
                jpeg = state.jpeg()
                if jpeg is not None:
                    yield (
                        b"--" + _BOUNDARY.encode() + b"\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    )
                time.sleep(0.033)  # ~30fps push so the browser gets fresh frames promptly
        return StreamingResponse(
            gen(),
            media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        )

    @app.websocket("/live")
    async def live(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                await ws.send_json(state.snapshot())
                await asyncio.sleep(0.2)
        except WebSocketDisconnect:
            return

    @app.get("/api/history")
    def history():
        if store is None:
            return {"events": [], "summary": {}}
        t = time.localtime()
        today_start = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
        return {
            "events": store.recent_events(today_start),
            "summary": store.daily_summary(today_start),
        }

    @app.get("/api/presence")
    def presence():
        _empty_today = {
            "date": "",
            "total_seconds": 0.0,
            "session_count": 0,
            "first_sit_ts": None,
            "last_leave_ts": None,
            "active_seconds": 0,
            "idle_seconds": 0,
            "sessions": [],
            "tracked_ranges": [],
        }
        _empty = {
            "today": _empty_today,
            "by_hour": [{"hour": h, "seconds": 0} for h in range(24)],
            "by_day": [],
            "work_split": {"work_seconds": 0, "off_seconds": 0},
        }
        if store is None:
            return _empty

        from sentinel.presence import sessionize, summarize_day, tracked_ranges

        now = time.time()
        t = time.localtime(now)
        today_start = time.mktime(
            (t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)
        )
        today_date = f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"

        history_since = now - presence_cfg.history_days * 86400
        trend_since = now - presence_cfg.trend_days * 86400

        # Today — raw samples → sessionize → summarize
        today_samples = store.present_samples(today_start)
        sessions = sessionize(
            today_samples,
            gap_merge_s=presence_cfg.gap_merge_seconds,
            min_session_s=presence_cfg.min_session_seconds,
        )
        today_summary = summarize_day(sessions)
        t_ranges = tracked_ranges(today_samples)

        # Aggregations
        by_hour_raw = store.presence_by_hour_of_day(history_since)
        by_day_raw = store.presence_by_day(trend_since)
        work_split = store.work_hours_split(
            history_since,
            presence_cfg.work_start_hour,
            presence_cfg.work_end_hour,
        )

        # Active/idle second counts for today — from DB aggregation
        if hasattr(store, "active_idle_seconds"):
            _ai = store.active_idle_seconds(today_start)
        else:
            _ai = {"active_seconds": 0, "idle_seconds": 0}

        return {
            "today": {
                "date": today_date,
                "total_seconds": today_summary["total_seconds"],
                "session_count": today_summary["session_count"],
                "first_sit_ts": today_summary["first_sit_ts"],
                "last_leave_ts": today_summary["last_leave_ts"],
                "active_seconds": _ai["active_seconds"],
                "idle_seconds": _ai["idle_seconds"],
                "sessions": [
                    {"start_ts": s.start_ts, "end_ts": s.end_ts} for s in sessions
                ],
                "tracked_ranges": t_ranges,
            },
            "by_hour": [
                {"hour": h, "seconds": by_hour_raw.get(h, 0)} for h in range(24)
            ],
            "by_day": by_day_raw,
            "work_split": work_split,
        }

    @app.post("/api/ask")
    async def ask(request: Request):
        """Answer a spoken or typed question about desk stats.

        Accepts:
          - ``multipart/form-data`` with an ``audio`` file field: the audio is
            saved to a temp file, transcribed by faster-whisper, then answered.
          - ``application/json`` with a ``{"question": "..."}`` body: skips STT
            and goes straight to the LLM.

        Returns ``{"question": str, "answer": str}`` on success, or
        ``{"error": str}`` for user-facing errors (empty transcript, Ollama
        down).  503 when ``store`` is unavailable (no brief possible).
        """
        if store is None:
            return JSONResponse(
                {"error": "Store unavailable — tracker not running."},
                status_code=503,
            )

        question = ""
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type:
            form = await request.form()
            audio_field = form.get("audio")
            if audio_field is None:
                return JSONResponse(
                    {"error": "No audio field in multipart form."},
                    status_code=400,
                )

            # Determine a useful suffix (faster-whisper/PyAV uses it for
            # container detection; fall back to .webm which MediaRecorder uses).
            suffix = ".webm"
            filename = getattr(audio_field, "filename", None) or ""
            if "." in filename:
                suffix = "." + filename.rsplit(".", 1)[-1]

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp_path = tmp.name
                    content = await audio_field.read()
                    tmp.write(content)

                # Whisper is blocking — run it off the event loop so the camera
                # stream and live WebSocket don't freeze during transcription.
                question = await asyncio.to_thread(
                    lambda p=tmp_path: _get_transcriber(voice_cfg.whisper_model).transcribe_file(p)
                )
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        else:
            # Fall through to JSON regardless of content-type header accuracy.
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {"error": "Expected JSON body with {\"question\": \"...\"}"},
                    status_code=400,
                )
            question = (body.get("question") or "").strip()

        if not question.strip():
            return JSONResponse({"error": "I didn't catch that."})

        now = time.time()
        try:
            # Brief-build + (optional news fetch) + Ollama are all blocking —
            # run them in a worker thread to keep the event loop responsive.
            answer = await asyncio.to_thread(
                _answer_pipeline, question, store, voice_cfg, now
            )
        except Exception as exc:
            log.warning("Ollama error on /api/ask: %s", exc)
            return JSONResponse({"error": "My brain's offline right now."})

        # Speak the answer locally via macOS `say` — the same nice system voice
        # the coach uses (volume=None: don't override the user's current volume).
        # Fire-and-forget so the HTTP response (text) returns immediately.
        threading.Thread(
            target=speak_mac, args=(answer, None), daemon=True
        ).start()

        return {"question": question, "answer": answer}

    if static_dir is not None and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app
