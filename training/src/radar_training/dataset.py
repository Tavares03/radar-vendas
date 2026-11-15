"""Leitura do dataset sintético (``radar-synth generate``) para o treino e a avaliação.

O classificador treina com o texto **mascarado** pelas entidades anotadas (``[CPF]``,
``[NOME_PESSOA]``…), porque é esse texto que ele recebe em produção: a análise só enxerga
mensagens mascaradas.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from radar.privacy.detection import PiiSpan
from radar.privacy.masking import mask
from radar.taxonomy import CLASSIFIER_LABELS, PiiType, SenderRole

SPLITS = ("train", "validation", "test", "desafio")

Entity = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class NerExample:
    id: str
    text: str
    entities: tuple[Entity, ...]
    sector: str


@dataclass(frozen=True, slots=True)
class MessageExample:
    id: str
    conversation_id: str
    sender: SenderRole
    #: Texto mascarado pelas entidades anotadas.
    text: str
    labels: frozenset[str]
    sector: str


def default_dataset_dir(root: Path = Path("data/generated")) -> Path:
    """A pasta do dataset na versão atual do gerador."""
    from radar_synth.dataset import dataset_version

    path = root / dataset_version()
    if not (path / "manifest.json").is_file():
        raise FileNotFoundError(
            f"Dataset {path} não encontrado. Gere com: uv run radar-synth generate"
        )
    return path


def dataset_manifest(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    return data


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_ner(path: Path, split: str) -> list[NerExample]:
    return [
        NerExample(
            id=row["id"],
            text=row["text"],
            entities=tuple((e["type"], e["start"], e["end"]) for e in row["entities"]),
            sector=row["sector"],
        )
        for row in _rows(path / "ner" / f"{split}.jsonl")
    ]


def masked_text(text: str, entities: tuple[Entity, ...]) -> str:
    spans = [PiiSpan(PiiType(kind), start, end, text[start:end]) for kind, start, end in entities]
    return mask(text, spans).text


def load_messages(path: Path, split: str) -> list[MessageExample]:
    ner = {example.id: example for example in load_ner(path, split)}
    examples = []
    for row in _rows(path / "messages" / f"{split}.jsonl"):
        gold = ner[row["id"]]
        if gold.text != row["text"]:
            raise ValueError(f"{row['id']}: texto diferente entre messages/ e ner/")
        examples.append(
            MessageExample(
                id=row["id"],
                conversation_id=row["conversation_id"],
                sender=SenderRole(row["sender"]),
                text=masked_text(row["text"], gold.entities),
                labels=frozenset(label for label in row["labels"] if label in CLASSIFIER_LABELS),
                sector=row["sector"],
            )
        )
    return examples
