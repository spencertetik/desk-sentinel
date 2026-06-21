"""voice/stt.py — speech-to-text via faster-whisper.

Usage:
    t = Transcriber("base.en")
    text = t.transcribe(audio_float32_16k)

The model is loaded once at construction time and reused on every call.
"""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger("desk_sentinel.voice.stt")


class Transcriber:
    """Wraps a faster-whisper WhisperModel for repeated transcription.

    Args:
        model_size: faster-whisper model identifier, e.g. ``"base.en"``.
        device: ``"cpu"`` or ``"cuda"``.
        compute_type: quantisation type passed to faster-whisper.
    """

    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        from faster_whisper import WhisperModel  # deferred: heavy import

        log.info("Loading Whisper model %r on %s …", model_size, device)
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        log.info("Whisper model loaded.")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a 16 kHz mono float32 audio array.

        Args:
            audio: 1-D float32 numpy array sampled at 16 000 Hz.

        Returns:
            Transcribed text, stripped of leading/trailing whitespace.
            Returns an empty string if no speech is detected.
        """
        audio = np.asarray(audio, dtype=np.float32)
        segments, _info = self._model.transcribe(
            audio,
            beam_size=5,
            language="en",
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe_file(self, path: str) -> str:
        """Transcribe an audio file at the given path.

        faster-whisper's ``WhisperModel.transcribe`` accepts a file path and
        decodes the container natively via bundled PyAV — no manual ffmpeg step
        needed.

        Args:
            path: path to an audio file (any format supported by faster-whisper
                / PyAV, e.g. webm, mp4, wav, ogg, mp3).

        Returns:
            Transcribed text, stripped of leading/trailing whitespace.
            Returns an empty string if no speech is detected.
        """
        segments, _info = self._model.transcribe(
            path,
            beam_size=5,
            language="en",
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
