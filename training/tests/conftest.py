"""Dataset minúsculo no formato do ``radar-synth generate``, com o vocabulário dos modelos de teste."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# (remetente, texto, rótulos, entidades); repetidas para o TF-IDF ter frequência mínima.
MESSAGES: list[tuple[str, str, list[str], list[tuple[str, int, int]]]] = [
    ("cliente", "meu nome e joana silva", [], [("NOME_PESSOA", 11, 22)]),
    ("vendedor", "pode pagar no pix", ["pagamento_fora_canal"], []),
    ("cliente", "achei caro", ["objecao_preco"], []),
    ("cliente", "oi tudo bem", [], []),
    ("vendedor", "fala com joana", [], [("NOME_PESSOA", 9, 14)]),
]


def write_dataset(root: Path, copies: int = 4) -> Path:
    for folder in ("messages", "ner"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    for split in ("train", "validation", "test", "desafio"):
        message_rows: list[dict[str, Any]] = []
        ner_rows: list[dict[str, Any]] = []
        for copy in range(copies if split == "train" else 1):
            for index, (sender, text, labels, entities) in enumerate(MESSAGES):
                row_id = f"{split}-{copy}#{index}"
                message_rows.append(
                    {"id": row_id, "conversation_id": f"{split}-{copy}", "sender": sender, "sector": "generico",
                     "text": text, "labels": labels}
                )  # fmt: skip
                ner_rows.append(
                    {"id": row_id, "text": text, "sector": "generico",
                     "entities": [{"type": t, "start": s, "end": e} for t, s, e in entities]}
                )  # fmt: skip
        for folder, rows in (("messages", message_rows), ("ner", ner_rows)):
            with (root / folder / f"{split}.jsonl").open("w", encoding="utf-8") as handle:
                handle.writelines(json.dumps(row) + "\n" for row in rows)
    (root / "manifest.json").write_text(json.dumps({"version": "teste+0"}), encoding="utf-8")
    return root


@pytest.fixture
def tiny_dataset(tmp_path: Path) -> Path:
    return write_dataset(tmp_path / "dataset")


TRAINING = {
    "config": {
        "name": "x", "task": "ner", "version": "1.0", "base_model": "base/teste", "base_license": "MIT",
        "seed": 1, "max_length": 32, "stride": 4, "batch_size": 8, "epochs": 2, "learning_rate": 5e-5,
        "warmup_ratio": 0.1, "weight_decay": 0.01, "patience": 1,
    },
    "best_epoch": 2, "best_score": 0.9, "seconds": 120.0, "hardware": "CPU",
    "history": [{"epoch": 1, "loss": 0.5, "score": 0.8}, {"epoch": 2, "loss": 0.2, "score": 0.9}],
}  # fmt: skip


@pytest.fixture
def training_info() -> dict[str, Any]:
    return json.loads(json.dumps(TRAINING))
