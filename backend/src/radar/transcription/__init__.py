"""Transcrição de áudios (local, com faster-whisper)."""

from __future__ import annotations

from radar.config import get_settings
from radar.transcription.base import AudioTooLong, Transcriber, Transcript, TranscriptionError
from radar.transcription.whisper import FasterWhisperTranscriber

__all__ = [
    "AudioTooLong",
    "FasterWhisperTranscriber",
    "Transcriber",
    "Transcript",
    "TranscriptionError",
    "get_transcriber",
    "set_transcriber",
]

_transcriber: Transcriber | None = None
_override: Transcriber | None = None
_has_override = False


def set_transcriber(transcriber: Transcriber | None, *, clear: bool = False) -> None:
    """Troca o transcritor do processo (testes e demos). ``clear=True`` volta ao padrão."""
    global _override, _has_override, _transcriber
    if clear:
        _override, _has_override, _transcriber = None, False, None
    else:
        _override, _has_override = transcriber, True


def get_transcriber() -> Transcriber | None:
    """Transcritor configurado, ou ``None`` se a transcrição estiver desligada."""
    global _transcriber
    if _has_override:
        return _override
    settings = get_settings()
    if not settings.transcription_enabled:
        return None
    if _transcriber is None:
        _transcriber = FasterWhisperTranscriber(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            max_minutes=settings.max_audio_minutes,
        )
    return _transcriber
