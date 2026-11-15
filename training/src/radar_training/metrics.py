"""Métricas de avaliação: por classe, micro e macro, matriz de confusão e limiares.

NER tem duas leituras:

- **exata** (tipo e fronteiras iguais): a métrica usual de NER, para comparar com outros modelos;
- **cobertura da máscara**: o que importa para a LGPD. Uma entidade conta como protegida se todos
  os caracteres dela ficaram debaixo de alguma máscara, qualquer que seja o tipo previsto.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

Entity = tuple[str, int, int]
NONE = "nenhum"


@dataclass(slots=True)
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def support(self) -> int:
        return self.tp + self.fn

    def as_dict(self) -> dict[str, float | int]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "support": self.support,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


@dataclass(slots=True)
class Report:
    """Métricas por classe, micro e macro (média das classes com exemplos)."""

    per_class: dict[str, Score] = field(default_factory=dict)

    @property
    def micro(self) -> Score:
        return Score(
            sum(s.tp for s in self.per_class.values()),
            sum(s.fp for s in self.per_class.values()),
            sum(s.fn for s in self.per_class.values()),
        )

    @property
    def macro_f1(self) -> float:
        scored = [s.f1 for s in self.per_class.values() if s.support]
        return sum(scored) / len(scored) if scored else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "micro": self.micro.as_dict(),
            "macro_f1": round(self.macro_f1, 4),
            "per_class": {name: score.as_dict() for name, score in self.per_class.items()},
        }


# ---------------------------------------------------------------- NER
def span_report(
    gold: Sequence[Iterable[Entity]], predicted: Sequence[Iterable[Entity]], types: Sequence[str]
) -> Report:
    """Acerto exato: mesmo tipo, mesmo início e mesmo fim."""
    report = Report({kind: Score() for kind in types})
    for gold_spans, predicted_spans in zip(gold, predicted, strict=True):
        g, p = set(gold_spans), set(predicted_spans)
        for kind, start, end in g:
            report.per_class[kind].tp += (kind, start, end) in p
            report.per_class[kind].fn += (kind, start, end) not in p
        for kind, _start, _end in p - g:
            report.per_class.setdefault(kind, Score()).fp += 1
    return report


def _covered(spans: Iterable[Entity]) -> set[int]:
    return {i for _, start, end in spans for i in range(start, end)}


def mask_coverage(
    gold: Sequence[Iterable[Entity]], predicted: Sequence[Iterable[Entity]], types: Sequence[str]
) -> dict[str, object]:
    """Entidades inteiramente mascaradas (qualquer tipo) e precisão por caractere da máscara."""
    protected: Counter[str] = Counter()
    total: Counter[str] = Counter()
    masked_chars = correct_chars = 0
    for gold_spans, predicted_spans in zip(gold, predicted, strict=True):
        g, p = list(gold_spans), list(predicted_spans)
        covered = _covered(p)
        gold_chars = _covered(g)
        masked_chars += len(covered)
        correct_chars += len(covered & gold_chars)
        for kind, start, end in g:
            total[kind] += 1
            protected[kind] += all(i in covered for i in range(start, end))
    per_type = {
        kind: round(protected[kind] / total[kind], 4) if total[kind] else None for kind in types
    }
    all_total = sum(total.values())
    return {
        "entities_fully_masked": round(sum(protected.values()) / all_total, 4)
        if all_total
        else None,
        "char_precision": round(correct_chars / masked_chars, 4) if masked_chars else None,
        "per_type": per_type,
    }


def ner_confusion(
    gold: Sequence[Iterable[Entity]], predicted: Sequence[Iterable[Entity]], types: Sequence[str]
) -> dict[str, dict[str, int]]:
    """Linha = tipo verdadeiro, coluna = tipo previsto (pela maior sobreposição).

    ``nenhum`` na coluna é entidade perdida; ``nenhum`` na linha é alarme falso.
    """
    names = [*types, NONE]
    matrix = {row: dict.fromkeys(names, 0) for row in names}
    for gold_spans, predicted_spans in zip(gold, predicted, strict=True):
        g, p = list(gold_spans), list(predicted_spans)
        for kind, start, end in g:
            overlaps = [(min(end, pe) - max(start, ps), pk) for pk, ps, pe in p]
            best = max(overlaps, default=(0, NONE))
            matrix[kind][best[1] if best[0] > 0 else NONE] += 1
        for pk, ps, pe in p:
            if not any(min(pe, ge) > max(ps, gs) for _, gs, ge in g):
                matrix[NONE][pk] += 1
    return matrix


# ---------------------------------------------------------------- classificador
def multilabel_report(
    gold: Sequence[Iterable[str]], predicted: Sequence[Iterable[str]], labels: Sequence[str]
) -> Report:
    report = Report({label: Score() for label in labels})
    for gold_labels, predicted_labels in zip(gold, predicted, strict=True):
        g, p = set(gold_labels), set(predicted_labels)
        for label in labels:
            score = report.per_class[label]
            score.tp += label in g and label in p
            score.fp += label not in g and label in p
            score.fn += label in g and label not in p
    return report


def label_confusion(
    gold: Sequence[Iterable[str]], predicted: Sequence[Iterable[str]], labels: Sequence[str]
) -> dict[str, dict[str, int]]:
    """Linha = rótulo verdadeiro, coluna = o que o modelo disse no lugar dele.

    Rótulo acertado conta na diagonal. Rótulo perdido conta em cada rótulo errado previsto na mesma
    mensagem (ou em ``nenhum``); rótulo previsto em mensagem sem rótulo conta na linha ``nenhum``.
    """
    names = [*labels, NONE]
    matrix = {row: dict.fromkeys(names, 0) for row in names}
    for gold_labels, predicted_labels in zip(gold, predicted, strict=True):
        g, p = set(gold_labels), set(predicted_labels)
        wrong = sorted(p - g)
        for label in g:
            if label in p:
                matrix[label][label] += 1
            else:
                for other in wrong or [NONE]:
                    matrix[label][other] += 1
        if not g:
            for label in wrong:
                matrix[NONE][label] += 1
    return matrix


#: Limiares testados: 0,10, 0,15… 0,95.
THRESHOLD_GRID: tuple[float, ...] = tuple(round(0.1 + 0.05 * i, 2) for i in range(18))


#: Limiar de um rótulo desligado: nenhuma probabilidade chega lá.
DISABLED_THRESHOLD = 1.01


def is_disabled(threshold: float) -> bool:
    return threshold > 1.0


def tune_thresholds(
    gold: Sequence[Iterable[str]],
    probabilities: NDArray[np.float32],
    labels: Sequence[str],
    grid: Sequence[float] = THRESHOLD_GRID,
    *,
    min_precision: float = 0.0,
) -> dict[str, float]:
    """Limiar por rótulo que maximiza o F1 na validação (empate: o mais perto de 0,5).

    Com ``min_precision``, só valem limiares em que o rótulo acerta pelo menos essa fração do
    que aponta; o rótulo que não chega lá em limiar nenhum fica desligado
    (:data:`DISABLED_THRESHOLD`). É o que vai para produção: um alerta de risco apontado só
    pelo modelo, sem LLM para conferir, não pode errar mais do que acerta.
    """
    gold_sets = [set(g) for g in gold]
    thresholds = {}
    for column, label in enumerate(labels):
        truth = np.array([label in g for g in gold_sets])
        if not truth.any():
            thresholds[label] = 0.5
            continue
        best: tuple[float, float, float] | None = None
        for threshold in grid:
            guess = probabilities[:, column] >= threshold
            tp = int((guess & truth).sum())
            fp = int((guess & ~truth).sum())
            fn = int((~guess & truth).sum())
            if min_precision > 0 and (tp == 0 or tp / (tp + fp) < min_precision):
                continue
            f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
            candidate = (round(f1, 6), -abs(threshold - 0.5), threshold)
            best = candidate if best is None else max(best, candidate)
        thresholds[label] = float(best[2]) if best is not None else DISABLED_THRESHOLD
    return thresholds


def apply_thresholds(
    probabilities: NDArray[np.float32], labels: Sequence[str], thresholds: dict[str, float]
) -> list[set[str]]:
    return [
        {label for label, p in zip(labels, row, strict=True) if p >= thresholds.get(label, 0.5)}
        for row in probabilities
    ]
