"""Transcrição local com faster-whisper (CTranslate2). Nenhum áudio sai da máquina."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from radar.logs import get_logger
from radar.transcription.base import AudioTooLong, Transcript, TranscriptionError

log = get_logger(__name__)

SAMPLE_RATE = 16_000


def decode_audio(path: Path, *, max_seconds: float | None = None) -> NDArray[np.float32]:
    """Decodifica ``.opus``, ``.ogg``, ``.m4a``, ``.mp3``… para mono 16 kHz em ``float32``.

    Usa PyAV (FFmpeg embutido), então não depende de ffmpeg instalado. A decodificação é feita
    aqui, e não dentro do faster-whisper, para podermos recusar áudios longos antes de gastar
    memória com eles.
    """
    import av

    limit = None if max_seconds is None else int(max_seconds * SAMPLE_RATE)
    chunks: list[NDArray[np.int16]] = []
    total = 0
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise TranscriptionError("O arquivo não tem faixa de áudio.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

            def collect(frames: Any) -> None:
                nonlocal total
                for frame in frames:
                    samples = frame.to_ndarray().reshape(-1)
                    chunks.append(samples)
                    total += samples.shape[0]

            for frame in container.decode(audio=0):
                collect(resampler.resample(frame))
                if limit is not None and total > limit:
                    raise AudioTooLong(
                        f"Áudio com mais de {max_seconds / 60:.0f} min não é transcrito."
                        if max_seconds
                        else "Áudio longo demais."
                    )
            collect(resampler.resample(None))
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Não foi possível ler o áudio: {exc}") from exc
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class FasterWhisperTranscriber:
    """Carrega o modelo na primeira transcrição e o mantém em memória."""

    def __init__(
        self,
        model_name: str = "small",
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        max_minutes: int = 30,
        language: str | None = "pt",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.max_seconds = max_minutes * 60
        self.language = language
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            log.info("whisper_carregando", model=self.model_name, device=self.device)
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def transcribe(self, path: Path) -> Transcript:
        audio = decode_audio(path, max_seconds=self.max_seconds)
        duration = audio.shape[0] / SAMPLE_RATE
        if duration < 0.2:
            return Transcript("", self.language or "", duration, self._label)
        try:
            # Um áudio por vez: o modelo não é seguro para uso concorrente.
            with self._lock:
                segments, info = self._load().transcribe(
                    audio,
                    language=self.language,
                    vad_filter=True,
                    beam_size=5,
                    condition_on_previous_text=False,
                )
                # `segments` é um gerador: a transcrição acontece ao iterar.
                text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:
            raise TranscriptionError(f"Falha ao transcrever o áudio: {exc}") from exc
        return Transcript(
            text=text,
            language=str(info.language or self.language or ""),
            duration_seconds=round(duration, 2),
            model=self._label,
        )

    @property
    def _label(self) -> str:
        return f"faster-whisper-{self.model_name}"
