"""NER de dados pessoais (``pii-ner-ptbr``) em ONNX.

O treino (``radar_training``) usa as mesmas funções de rótulo e de decodificação daqui, então a
métrica medida no treino é a do que roda em produção.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from radar.ml.bundle import ModelBundle, softmax
from radar.privacy.detection import PiiSpan
from radar.taxonomy import PII_TYPES, PiiType

#: Rótulos BIO na ordem das saídas do modelo.
NER_LABELS: tuple[str, ...] = ("O", *(f"{p}-{t}" for t in PII_TYPES for p in ("B", "I")))


@dataclass(frozen=True, slots=True)
class EntitySpan:
    type: str
    start: int
    end: int
    score: float


def token_labels(
    offsets: Sequence[tuple[int, int]],
    special: Sequence[int],
    entities: Iterable[tuple[str, int, int]],
) -> list[str | None]:
    """Rótulo BIO de cada token a partir das entidades por caractere (``None`` = ignorar).

    Um token é da entidade se tiver algum caractere dentro dela; o primeiro é ``B-``.
    """
    labels: list[str | None] = [
        None if s or a == b else "O" for (a, b), s in zip(offsets, special, strict=True)
    ]
    for kind, start, end in sorted(entities, key=lambda e: e[1]):
        first = True
        for i, ((a, b), s) in enumerate(zip(offsets, special, strict=True)):
            if s or a == b or max(a, start) >= min(b, end):
                continue
            labels[i] = f"{'B' if first else 'I'}-{kind}"
            first = False
    return labels


def decode_bio(
    text: str,
    offsets: Sequence[tuple[int, int]],
    special: Sequence[int],
    probabilities: NDArray[np.float32],
    labels: Sequence[str],
) -> list[EntitySpan]:
    """Junta os tokens rotulados em trechos do texto.

    Tolerante a erros pequenos do modelo: um pedaço de palavra rotulado ``B-`` logo depois de
    outro do mesmo tipo continua o trecho, e o trecho cresce até a palavra inteira (nunca sobra
    meio nome sem máscara).
    """
    spans: list[list[Any]] = []
    current: list[Any] | None = None
    for (a, b), is_special, row in zip(offsets, special, probabilities, strict=False):
        if is_special or a == b:
            continue
        index = int(row.argmax())
        label = labels[index]
        if label == "O":
            current = None
            continue
        prefix, kind = label.split("-", 1)
        if current is not None and kind == current[0] and (prefix == "I" or a <= current[2]):
            current[2] = max(current[2], b)
            current[3].append(float(row[index]))
            continue
        current = [kind, a, b, [float(row[index])]]
        spans.append(current)

    result: list[EntitySpan] = []
    for kind, start, end, scores in spans:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        while start > 0 and text[start - 1].isalnum():
            start -= 1
        while end < len(text) and text[end].isalnum():
            end += 1
        if start < end:
            result.append(EntitySpan(kind, start, end, sum(scores) / len(scores)))
    return result


class OnnxPiiNer:
    """Implementa ``radar.privacy.detector.NerModel`` com um modelo ONNX."""

    def __init__(
        self, path: Path, *, threads: int = 0, batch_size: int = 32, onnx_file: str | None = None
    ) -> None:
        self.bundle = ModelBundle(path, threads=threads, onnx_file=onnx_file)
        manifest = self.bundle.manifest
        if manifest.task != "ner":
            raise ValueError(f"{path} não é um modelo de NER (task={manifest.task})")
        unknown = {label.split("-", 1)[-1] for label in manifest.labels if label != "O"} - set(
            PII_TYPES
        )
        if unknown:
            raise ValueError(f"Tipos de dado pessoal desconhecidos no modelo: {sorted(unknown)}")
        self.name = manifest.tag
        self.batch_size = batch_size
        self.bundle.tokenizer.enable_truncation(manifest.max_length, stride=manifest.stride)

    def predict(self, texts: Sequence[str]) -> list[list[PiiSpan]]:
        windows: list[tuple[int, Any]] = []
        for index, text in enumerate(texts):
            if not text.strip():
                continue
            encoding = self.bundle.tokenizer.encode(text)
            windows.extend((index, window) for window in (encoding, *encoding.overflowing))

        found: list[list[EntitySpan]] = [[] for _ in texts]
        labels = self.bundle.manifest.labels
        for begin in range(0, len(windows), self.batch_size):
            batch = windows[begin : begin + self.batch_size]
            probabilities = softmax(self.bundle.run([w for _, w in batch]))
            for (index, window), rows in zip(batch, probabilities, strict=True):
                size = len(window.ids)
                found[index].extend(
                    decode_bio(
                        texts[index],
                        window.offsets,
                        window.special_tokens_mask,
                        rows[:size],
                        labels,
                    )
                )

        return [
            [
                PiiSpan(
                    PiiType(s.type), s.start, s.end, texts[index][s.start : s.end], "ner", s.score
                )
                for s in merge_overlapping(spans)
            ]
            for index, spans in enumerate(found)
        ]


def merge_overlapping(spans: Iterable[EntitySpan]) -> list[EntitySpan]:
    """Une trechos do mesmo tipo que se sobrepõem (a mesma entidade vista por duas janelas)."""
    merged: list[EntitySpan] = []
    for span in sorted(spans, key=lambda s: (s.start, -s.end)):
        previous = next((m for m in reversed(merged) if m.type == span.type), None)
        if previous is not None and span.start < previous.end:
            merged[merged.index(previous)] = EntitySpan(
                span.type,
                previous.start,
                max(previous.end, span.end),
                max(previous.score, span.score),
            )
        else:
            merged.append(span)
    return merged
