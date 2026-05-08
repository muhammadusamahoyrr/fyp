"""Singleton Whisper service — one model instance for the entire process."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import threading

import soundfile as sf

logger = logging.getLogger(__name__)

_MODEL_SIZE   = "base"
_DEVICE       = "cpu"
_COMPUTE_TYPE = "int8"
_BEAM_SIZE    = 5

# ISO 639-1 codes relevant to Pakistani users
_LANG_NAMES: dict[str, str] = {
    "ur": "Urdu",
    "en": "English",
    "pa": "Punjabi",
    "sd": "Sindhi",
    "ps": "Pashto",
    "hi": "Hindi",
    "ar": "Arabic",
    "fa": "Persian",
}


class WhisperService:
    """Thread-safe singleton that holds the loaded WhisperModel."""

    _instance: WhisperService | None = None
    _lock = threading.Lock()   # guards model init (sync / thread-pool context)
    _model = None

    # ── Singleton ──────────────────────────────────────────────────────────────
    def __new__(cls) -> WhisperService:
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._alock = asyncio.Lock()   # serialises inference (async / event-loop context)
            cls._instance = inst
        return cls._instance

    # ── Lazy model property ────────────────────────────────────────────────────
    @property
    def model(self):
        """Auto-loads on first access (thread-safe via _lock)."""
        if self._model is None:
            self.load()
        return self._model

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    def load(self) -> None:
        """Load model into memory (idempotent, thread-safe)."""
        with self._lock:
            if self._model is not None:
                return
            logger.info("Loading Whisper '%s' on %s …", _MODEL_SIZE, _DEVICE)
            from faster_whisper import WhisperModel
            self._model = WhisperModel(_MODEL_SIZE, device=_DEVICE, compute_type=_COMPUTE_TYPE)
            logger.info("Whisper model ready.")

    async def warmup(self) -> None:
        """Fire-and-forget preload — call once from FastAPI lifespan."""
        asyncio.create_task(asyncio.to_thread(self.load))

    # ── Audio decoding ─────────────────────────────────────────────────────────
    def _decode(self, audio_bytes: bytes, filename: str) -> tuple:
        """
        Decode audio bytes into a source faster-whisper can consume.

        Returns (source, tmp_path):
          source    — float32 numpy array (soundfile) or str file path (ffmpeg fallback)
          tmp_path  — path to delete after inference, or None when source is an array
        """
        try:
            data, _sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
            array = data.mean(axis=1) if data.ndim > 1 else data
            return array, None
        except Exception:
            pass

        # Fallback: temp file for ffmpeg-backed formats (webm / ogg / mp4)
        suffix = os.path.splitext(filename)[1] or ".webm"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(audio_bytes)
            tmp.flush()
        finally:
            tmp.close()
        return tmp.name, tmp.name

    # ── Transcription (sync — runs in thread pool) ─────────────────────────────
    def transcribe(self, audio_bytes: bytes, filename: str = "audio.wav") -> dict:
        """
        Transcribe raw audio bytes (blocking — call via transcribe_async).

        Returns:
          transcript           — full text string
          language             — ISO 639-1 code   (e.g. "ur", "en")
          language_name        — display name     (e.g. "Urdu", "English")
          language_probability — confidence 0–1
        """
        source, tmp_path = self._decode(audio_bytes, filename)
        try:
            segments, info = self.model.transcribe(source, language=None, beam_size=_BEAM_SIZE)
            transcript = " ".join(seg.text.strip() for seg in segments).strip()
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        lang = info.language
        return {
            "transcript": transcript,
            "language": lang,
            "language_name": _LANG_NAMES.get(lang, lang.upper()),
            "language_probability": round(info.language_probability, 3),
        }

    # ── Transcription (async — use this from route handlers) ──────────────────
    async def transcribe_async(self, audio_bytes: bytes, filename: str = "audio.wav") -> dict:
        """
        Queue-protected transcription for concurrent HTTP requests.

        _alock serialises inference so CPU is never saturated by parallel calls.
        Callers await in line — no request is dropped, no OOM from parallel models.
        """
        async with self._alock:
            return await asyncio.to_thread(self.transcribe, audio_bytes, filename)


# Module-level singleton — import this everywhere
whisper_service = WhisperService()
