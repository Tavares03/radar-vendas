"""Detector de dados pessoais em camadas.

1. ``regex``: padrões, validadores (CPF, CNPJ, telefone…) e contexto;
2. ``participantes``: os nomes de quem está na conversa (o export entrega isso de graça);
3. ``ner``: o modelo próprio de NER para PT-BR (``pii-ner-ptbr``), quando disponível.

Cada camada é opcional na prática: se o NER falhar ou não existir, a máscara por regex continua.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from radar.config import get_settings
from radar.logs import get_logger
from radar.privacy.detection import PiiSpan, detect_known_names, detect_regex, resolve_spans
from radar.privacy.masking import MaskedText, mask
from radar.taxonomy import PiiType

log = get_logger(__name__)


class NerModel(Protocol):
    """Modelo de NER de dados pessoais (implementado na fase de modelos próprios)."""

    name: str

    def predict(self, texts: Sequence[str]) -> list[list[PiiSpan]]:
        """Um lista de trechos (``source="ner"``) por texto, na mesma ordem."""
        ...


class PiiDetector:
    def __init__(self, ner: NerModel | None = None) -> None:
        self.ner = ner

    @property
    def layers(self) -> tuple[str, ...]:
        base = ("regex", "participantes")
        return (*base, f"ner:{self.ner.name}") if self.ner is not None else base

    def _ner_spans(self, texts: Sequence[str]) -> list[list[PiiSpan]]:
        if self.ner is None or not any(texts):
            return [[] for _ in texts]
        try:
            predicted = self.ner.predict(texts)
        except Exception:
            log.exception("ner_falhou", modelo=self.ner.name, textos=len(texts))
            return [[] for _ in texts]
        if len(predicted) != len(texts):
            log.error("ner_resposta_invalida", esperado=len(texts), recebido=len(predicted))
            return [[] for _ in texts]
        return predicted

    def detect_many(
        self,
        texts: Sequence[str],
        *,
        known_names: Sequence[str] = (),
        mask_names: bool = True,
    ) -> list[list[PiiSpan]]:
        results = []
        for text, ner_spans in zip(texts, self._ner_spans(texts), strict=True):
            candidates = detect_regex(text) + list(ner_spans)
            if mask_names:
                candidates += detect_known_names(text, known_names)
            else:
                candidates = [s for s in candidates if s.type is not PiiType.NOME_PESSOA]
            results.append(resolve_spans(candidates, text))
        return results

    def detect(
        self, text: str, *, known_names: Sequence[str] = (), mask_names: bool = True
    ) -> list[PiiSpan]:
        return self.detect_many([text], known_names=known_names, mask_names=mask_names)[0]

    def mask_many(
        self,
        texts: Sequence[str],
        *,
        known_names: Sequence[str] = (),
        mask_names: bool = True,
    ) -> list[MaskedText]:
        detected = self.detect_many(texts, known_names=known_names, mask_names=mask_names)
        return [mask(text, spans) for text, spans in zip(texts, detected, strict=True)]

    def mask(
        self, text: str, *, known_names: Sequence[str] = (), mask_names: bool = True
    ) -> MaskedText:
        return self.mask_many([text], known_names=known_names, mask_names=mask_names)[0]


_ner_override: NerModel | None = None
_has_override = False


def set_ner_model(model: NerModel | None, *, clear: bool = False) -> None:
    """Troca o modelo de NER do processo (testes e demos). ``clear=True`` volta ao padrão."""
    global _ner_override, _has_override
    _ner_override, _has_override = (None, False) if clear else (model, True)


def _load_ner() -> NerModel | None:
    if _has_override:
        return _ner_override
    if get_settings().ner_model == "off":
        return None
    # O modelo próprio entra na fase 7 (radar.ml); até lá a camada fica de fora.
    return None


def get_pii_detector() -> PiiDetector:
    return PiiDetector(ner=_load_ner())
