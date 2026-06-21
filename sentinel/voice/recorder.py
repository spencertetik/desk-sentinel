"""voice/recorder.py — mic recording with RMS-based silence detection.

Public API:
  is_trailing_silence(rms_window, threshold) -> bool   # pure, unit-tested
  record_until_silence(...)               -> np.ndarray # uses sounddevice
"""
from __future__ import annotations

import logging
from collections import deque

import numpy as np

log = logging.getLogger("desk_sentinel.voice.recorder")

SAMPLE_RATE = 16_000      # Hz — matches Whisper's expected input rate
CHUNK_FRAMES = 512        # frames per sounddevice callback chunk


# ---------------------------------------------------------------------------
# Pure VAD helper (unit-tested)
# ---------------------------------------------------------------------------

def is_trailing_silence(rms_window: list[float], threshold: float) -> bool:
    """Return True when the most-recent RMS window suggests silence.

    Args:
        rms_window: a list of recent RMS energy values (one per audio chunk).
            If empty, returns True (treat no data as silence).
        threshold: RMS value below which a chunk is considered silent.

    Returns:
        ``True`` if **all** values in ``rms_window`` are below ``threshold``,
        i.e. the tail of the recording is consistently quiet.
        ``False`` if any value meets or exceeds ``threshold`` (speech present).
    """
    if not rms_window:
        return True
    return all(rms < threshold for rms in rms_window)


# ---------------------------------------------------------------------------
# Recording (integration — needs sounddevice + real mic)
# ---------------------------------------------------------------------------

def record_until_silence(
    max_seconds: float = 15.0,
    silence_timeout: float = 1.2,
    rms_threshold: float = 0.01,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Record from the default mic until trailing silence or max duration.

    Stops recording when the last ``silence_timeout`` seconds of audio are
    all below ``rms_threshold`` RMS, or when ``max_seconds`` is reached.

    Args:
        max_seconds: hard ceiling on recording length (seconds).
        silence_timeout: how many consecutive seconds of silence triggers stop.
        rms_threshold: RMS energy threshold below which a chunk = silence.
        sample_rate: capture sample rate; should match Whisper's 16 000 Hz.

    Returns:
        1-D float32 numpy array of the captured audio, normalised to [-1, 1].
        Returns a zero-length array if no audio was captured.

    Raises:
        RuntimeError: if the microphone cannot be opened.
    """
    try:
        import sounddevice as sd  # deferred: optional runtime dep
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is not installed; run `pip install sounddevice`."
        ) from exc

    chunks: list[np.ndarray] = []
    # How many chunks fit in silence_timeout?
    chunks_per_second = sample_rate / CHUNK_FRAMES
    silence_window_size = max(1, int(chunks_per_second * silence_timeout))
    rms_window: deque[float] = deque(maxlen=silence_window_size)
    max_chunks = int(max_seconds * chunks_per_second)
    stop_flag = [False]

    def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ARG001
        if status:
            log.debug("sounddevice status: %s", status)
        chunk = indata[:, 0].copy()          # mono
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        chunks.append(chunk)
        rms_window.append(rms)
        if len(chunks) >= max_chunks:
            stop_flag[0] = True
            raise sd.CallbackStop()
        if len(rms_window) == silence_window_size and is_trailing_silence(
            list(rms_window), rms_threshold
        ):
            stop_flag[0] = True
            raise sd.CallbackStop()

    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_FRAMES,
            callback=_callback,
        ):
            # Block until the callback raises CallbackStop
            while not stop_flag[0]:
                sd.sleep(50)
    except sd.PortAudioError as exc:
        raise RuntimeError(f"Microphone error: {exc}") from exc

    if not chunks:
        return np.array([], dtype=np.float32)
    return np.concatenate(chunks)
