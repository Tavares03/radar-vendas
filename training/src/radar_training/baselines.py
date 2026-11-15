"""Baselines para comparar com os modelos próprios.

- NER: o detector por regex, validadores e contexto que já roda em produção;
- classificador: as regras dos playbooks (o que roda em produção sem modelo) e TF-IDF com
  regressão logística (o "modelo clássico" mínimo);
- LLM zero-shot, pelo mesmo roteador da análise (``radar.llm``). O NER zero-shot recebe texto sem
  máscara, então a trava de privacidade só deixa ir para o Ollama local: mesmo com dados
  sintéticos, o projeto não abre exceção para mandar dado pessoal à nuvem.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cache
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from radar.playbooks import load_playbook
from radar.playbooks.engine import RuleEngine
from radar.privacy.detector import PiiDetector
from radar.taxonomy import CLASSIFIER_LABELS, LABELS_PT, PII_TYPES
from radar_training.dataset import MessageExample
from radar_training.metrics import Entity

if TYPE_CHECKING:
    from radar.llm.router import LLMRouter


# ---------------------------------------------------------------- regex (produção)
def regex_ner(texts: Sequence[str]) -> list[list[Entity]]:
    detector = PiiDetector(ner=None)
    return [[(s.type.value, s.start, s.end) for s in detector.detect(text)] for text in texts]


# ---------------------------------------------------------------- regras dos playbooks
@cache
def _engine(sector: str) -> RuleEngine:
    return RuleEngine(load_playbook(sector))


def rules_classifier(examples: Sequence[MessageExample]) -> list[set[str]]:
    return [
        {hit.type for hit in _engine(e.sector).evaluate_message(e.text, e.sender)}
        & set(CLASSIFIER_LABELS)
        for e in examples
    ]


# ---------------------------------------------------------------- TF-IDF + regressão logística
def _tfidf_text(example: MessageExample) -> str:
    return f"__{example.sender.value}__ {example.text}"


class TfidfBaseline:
    """N-gramas de caracteres e palavras, um classificador logístico por rótulo."""

    def __init__(self, seed: int = 20261114) -> None:
        self.seed = seed
        self.labels = list(CLASSIFIER_LABELS)
        self.pipeline: Any = None

    def fit(self, examples: Sequence[MessageExample]) -> TfidfBaseline:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.multiclass import OneVsRestClassifier
        from sklearn.pipeline import FeatureUnion, make_pipeline

        features = FeatureUnion(
            [
                ("palavras", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
                (
                    "caracteres",
                    TfidfVectorizer(
                        analyzer="char_wb", ngram_range=(2, 5), min_df=3, sublinear_tf=True
                    ),
                ),
            ]
        )
        model = OneVsRestClassifier(
            LogisticRegression(max_iter=2000, C=4.0, random_state=self.seed), n_jobs=-1
        )
        self.pipeline = make_pipeline(features, model)
        targets = np.array(
            [[label in e.labels for label in self.labels] for e in examples], dtype=int
        )
        self.pipeline.fit([_tfidf_text(e) for e in examples], targets)
        return self

    def predict_proba(self, examples: Sequence[MessageExample]) -> NDArray[np.float32]:
        if self.pipeline is None:
            raise RuntimeError("Treine antes (fit)")
        return np.asarray(
            self.pipeline.predict_proba([_tfidf_text(e) for e in examples]), dtype=np.float32
        )


# ---------------------------------------------------------------- LLM zero-shot
class _Labeled(BaseModel):
    id: int
    labels: list[str] = Field(default_factory=list)


class _ClassifierAnswer(BaseModel):
    messages: list[_Labeled] = Field(default_factory=list)


class _Found(BaseModel):
    type: str
    text: str


class _NerItem(BaseModel):
    id: int
    entities: list[_Found] = Field(default_factory=list)


class _NerAnswer(BaseModel):
    messages: list[_NerItem] = Field(default_factory=list)


_CLASSIFIER_SYSTEM = (
    "Você classifica mensagens de WhatsApp de vendas em português do Brasil. Para cada mensagem, "
    "devolva os rótulos que se aplicam (pode ser nenhum). Rótulos de vendedor: {seller}. Rótulos "
    "de cliente: {customer}. Use só os ids da lista. Responda em JSON: "
    '{{"messages": [{{"id": 0, "labels": ["..."]}}]}}.'
)

_NER_SYSTEM = (
    "Você encontra dados pessoais em mensagens de WhatsApp em português do Brasil. Tipos: {types}. "
    "Para cada mensagem, devolva cada dado pessoal com o tipo e o trecho exato, copiado do texto. "
    'Responda em JSON: {{"messages": [{{"id": 0, "entities": [{{"type": "CPF", "text": "..."}}]}}]}}.'
)


def _describe(labels: Sequence[str]) -> str:
    return "; ".join(f"{label} ({LABELS_PT.get(label, label)})" for label in labels)


def llm_classifier(
    examples: Sequence[MessageExample], router: LLMRouter, *, batch_size: int = 20
) -> list[set[str]]:
    from radar.taxonomy import CUSTOMER_LABELS, SELLER_LABELS

    system = _CLASSIFIER_SYSTEM.format(
        seller=_describe(sorted(SELLER_LABELS)), customer=_describe(sorted(CUSTOMER_LABELS))
    )
    return _batched(
        examples,
        batch_size,
        lambda batch: (
            router.complete_json(
                system=system,
                user="\n".join(f"{i}. [{e.sender.value}] {e.text}" for i, e in enumerate(batch)),
                schema=_ClassifierAnswer,
            ).value
        ),
        lambda answer, size: _classifier_sets(answer, size),
    )


def _classifier_sets(answer: _ClassifierAnswer, size: int) -> list[set[str]]:
    result: list[set[str]] = [set() for _ in range(size)]
    for item in answer.messages:
        if 0 <= item.id < size:
            result[item.id] = set(item.labels) & set(CLASSIFIER_LABELS)
    return result


def llm_ner(texts: Sequence[str], router: LLMRouter, *, batch_size: int = 20) -> list[list[Entity]]:
    system = _NER_SYSTEM.format(types=", ".join(PII_TYPES))
    batches = _batched(
        list(texts),
        batch_size,
        lambda batch: (
            router.complete_json(
                system=system,
                user="\n".join(f"{i}. {text}" for i, text in enumerate(batch)),
                schema=_NerAnswer,
            ).value
        ),
        lambda answer, size: [
            [(e.type, e.text) for e in _ner_items(answer, size)[i]] for i in range(size)
        ],
    )
    return [locate(text, found) for text, found in zip(texts, batches, strict=True)]


def _ner_items(answer: _NerAnswer, size: int) -> list[list[_Found]]:
    result: list[list[_Found]] = [[] for _ in range(size)]
    for item in answer.messages:
        if 0 <= item.id < size:
            result[item.id] = [e for e in item.entities if e.type in PII_TYPES]
    return result


def locate(text: str, found: Sequence[tuple[str, str]]) -> list[Entity]:
    """Posição de cada trecho devolvido pelo LLM (trecho que não está no texto é descartado)."""
    entities: list[Entity] = []
    for kind, value in found:
        value = value.strip()
        start = text.find(value) if value else -1
        if start >= 0:
            entities.append((kind, start, start + len(value)))
    return entities


def _batched[T, A, R](
    items: Sequence[T],
    batch_size: int,
    ask: Callable[[Sequence[T]], A],
    parse: Callable[[A, int], list[R]],
) -> list[R]:
    results: list[R] = []
    for begin in range(0, len(items), batch_size):
        batch = items[begin : begin + batch_size]
        results.extend(parse(ask(batch), len(batch)))
    return results
