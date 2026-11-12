"""Contrato de transcrição de áudio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class TranscriptionError(RuntimeError):
    """O áudio não pôde ser transcrito."""


class AudioTooLong(TranscriptionError):
    """O áudio passa do limite configurado (``RADAR_MAX_AUDIO_MINUTES``)."""


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    duration_seconds: float
    model: str


class Transcriber(Protocol):
    """Qualquer coisa que transforme um arquivo de áudio em texto."""

    def transcribe(self, path: Path) -> Transcript: ...
