"""voice/agent.py — orchestrates the push-to-talk voice loop.

Run via:
    python -m sentinel.voice

This module is import-guarded: if sounddevice or pynput are absent it still
imports cleanly (so tests and other importers don't break).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger("desk_sentinel.voice.agent")

# ---------------------------------------------------------------------------
# Try importing optional runtime deps; set flags so the agent can give a
# clear error at runtime rather than at module-import time.
# ---------------------------------------------------------------------------
try:
    import sounddevice as _sd  # noqa: F401
    _HAS_SOUNDDEVICE = True
except Exception:  # ImportError OR PortAudioError on headless envs
    _HAS_SOUNDDEVICE = False

try:
    from pynput import keyboard as _keyboard
    _HAS_PYNPUT = True
except Exception:
    _HAS_PYNPUT = False


class VoiceAgent:
    """Registers a global hotkey and runs the record → STT → LLM → TTS loop.

    Args:
        store: an open :class:`~sentinel.store.Store` (read-only is fine).
        config: loaded :class:`~sentinel.config.VoiceConfig`.
        shared_state: optional :class:`~sentinel.state.SharedState`; when
            present its snapshot is included in the brief for richer answers.
    """

    def __init__(self, store, config, shared_state=None):
        self._store = store
        self._cfg = config
        self._state = shared_state
        self._running = False

        # Lazy-init heavy objects (Whisper model) on first trigger
        self._transcriber = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_transcriber(self):
        if self._transcriber is None:
            from sentinel.voice.stt import Transcriber
            self._transcriber = Transcriber(model_size=self._cfg.whisper_model)
        return self._transcriber

    def _speak(self, text: str) -> None:
        from sentinel.nudges import speak_mac
        speak_mac(text, volume=None)

    def _on_hotkey(self) -> None:
        """Called by pynput on every hotkey press — runs the full voice turn."""
        log.info("Hotkey pressed — starting voice turn")
        self._speak("One sec.")

        # 1. Record
        try:
            if not _HAS_SOUNDDEVICE:
                raise RuntimeError("sounddevice not installed")
            from sentinel.voice.recorder import record_until_silence
            audio = record_until_silence(
                max_seconds=self._cfg.max_record_seconds,
                silence_timeout=self._cfg.silence_timeout,
            )
        except RuntimeError as exc:
            log.error("Mic error: %s", exc)
            self._speak("I couldn't access the microphone.")
            return

        if audio is None or len(audio) == 0:
            log.warning("No audio captured")
            self._speak("I didn't catch that.")
            return

        # 2. Transcribe
        try:
            t = self._get_transcriber()
            question = t.transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            log.error("Transcription failed: %s", exc)
            self._speak("I had trouble understanding that.")
            return

        if not question.strip():
            log.info("Empty transcript")
            self._speak("I didn't catch that.")
            return

        log.info("Transcribed: %r", question)

        # 3. Build brief
        try:
            from sentinel.voice.brief import gather_stats, build_brief
            now = time.time()
            stats = gather_stats(self._store, now)

            # Optionally enrich with live state
            if self._state is not None:
                try:
                    snap = self._state.snapshot()
                    posture = snap.get("posture")
                    stats["current_posture"] = posture
                    stats["current_sitting_seconds"] = snap.get("sitting_seconds")
                    stats["current_present"] = (posture != "away")
                except Exception:  # noqa: BLE001
                    pass

            brief = build_brief(stats, now)
        except Exception as exc:  # noqa: BLE001
            log.error("Brief build failed: %s", exc)
            self._speak("I couldn't read my stats right now.")
            return

        # 4. LLM answer
        try:
            from sentinel.voice.llm import answer as llm_answer
            reply = llm_answer(
                question=question,
                brief=brief,
                model=self._cfg.ollama_model,
                url=self._cfg.ollama_url,
            )
        except RuntimeError as exc:
            log.error("LLM error: %s", exc)
            self._speak("My brain's offline right now.")
            return

        if not reply:
            self._speak("I don't have an answer for that.")
            return

        # 5. Speak the reply
        log.info("Speaking: %r", reply)
        self._speak(reply)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Register the hotkey and block until KeyboardInterrupt."""
        if not _HAS_PYNPUT:
            raise RuntimeError(
                "pynput is not installed; run `pip install pynput`."
            )

        hotkey_str = self._cfg.hotkey
        log.info("Registering hotkey %r …", hotkey_str)

        self._running = True
        try:
            with _keyboard.GlobalHotKeys({hotkey_str: self._on_hotkey}) as h:
                log.info(
                    "Desk Sentinel Voice Agent running. Press %s to ask a question.",
                    hotkey_str,
                )
                h.join()
        except KeyboardInterrupt:
            log.info("Voice agent stopped.")
        finally:
            self._running = False
