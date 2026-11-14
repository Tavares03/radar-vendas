"""Troca os dados pessoais por marcadores do tipo (``[CPF]``, ``[NOME_PESSOA]``…).

O texto mascarado é o que o painel mostra por padrão e o único que pode ir para um LLM externo.
Os trechos (:class:`MaskedSpan`) apontam para os marcadores no texto *mascarado*, para o painel
destacá-los sem precisar do original.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from radar.privacy.detection import PiiSpan, resolve_spans
from radar.taxonomy import PiiType


def placeholder(kind: PiiType) -> str:
    return f"[{kind.value}]"


@dataclass(frozen=True, slots=True)
class MaskedSpan:
    """Posição de um marcador no texto mascarado."""

    type: PiiType
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "start": self.start, "end": self.end}


@dataclass(frozen=True, slots=True)
class MaskedText:
    text: str
    spans: tuple[MaskedSpan, ...] = ()
    #: O que foi encontrado no texto original. Fora do ``repr`` para não ir parar em log.
    found: tuple[PiiSpan, ...] = field(default=(), repr=False, compare=False)

    def span_dicts(self) -> list[dict[str, Any]]:
        return [span.to_dict() for span in self.spans]


def mask(text: str, spans: Sequence[PiiSpan]) -> MaskedText:
    """Aplica a máscara. Trechos sobrepostos são unidos antes (nada fica descoberto)."""
    resolved = resolve_spans(spans, text)
    if not resolved:
        return MaskedText(text)
    parts: list[str] = []
    masked_spans: list[MaskedSpan] = []
    cursor = 0
    length = 0
    for span in resolved:
        before = text[cursor : span.start]
        parts.append(before)
        length += len(before)
        marker = placeholder(span.type)
        masked_spans.append(MaskedSpan(span.type, length, length + len(marker)))
        parts.append(marker)
        length += len(marker)
        cursor = span.end
    parts.append(text[cursor:])
    return MaskedText("".join(parts), tuple(masked_spans), tuple(resolved))
