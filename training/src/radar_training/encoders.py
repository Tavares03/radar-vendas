"""Comparação rápida de encoders candidatos: mesma semente, mesmos dados, uma época de cada tarefa.

Não é o treino final: serve para escolher a base. Mede o F1 na validação das duas tarefas, o
tamanho e a latência em CPU (PyTorch fp32, uma mensagem por vez).
"""

from __future__ import annotations

import gc
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from radar_training.config import TrainConfig
from radar_training.dataset import MessageExample, NerExample
from radar_training.export import latency
from radar_training.train import (
    TrainResult,
    predict_classifier,
    predict_ner,
    train_classifier,
    train_ner,
)

#: Candidatos (licenças MIT, compatíveis com publicar os modelos em Apache-2.0).
CANDIDATES = (
    "neuralmind/bert-base-portuguese-cased",  # BERTimbau: PT-BR, texto formal (Wikipedia, web)
    "pablocosta/bertabaporu-base-uncased",  # BERTabaporu: PT-BR de redes sociais (tweets)
    "jhu-clsp/mmBERT-small",  # mmBERT: ModernBERT multilíngue, pequeno e rápido
)


def compare(
    candidates: Sequence[str],
    data: dict[str, Any],
    *,
    epochs: int,
    seed: int,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    import torch

    ner_train: Sequence[NerExample] = data["ner_train"]
    ner_validation: Sequence[NerExample] = data["ner_validation"]
    msg_train: Sequence[MessageExample] = data["msg_train"]
    msg_validation: Sequence[MessageExample] = data["msg_validation"]
    results = []
    for base in candidates:
        log(f"== {base}")
        row: dict[str, Any] = {"base_model": base}
        for task in ("ner", "classifier"):
            config = TrainConfig(
                name=f"comparacao-{task}", task=task, version="0", base_model=base, seed=seed,
                epochs=epochs, patience=epochs,
            )  # fmt: skip
            if task == "ner":
                result = train_ner(config, ner_train, ner_validation, log)
            else:
                result = train_classifier(config, msg_train, msg_validation, log)
            row[task] = {
                "validation_score": round(result.best_score, 4),
                "metric": "micro_f1_exato" if task == "ner" else "macro_f1",
                # Só as épocas: o tempo total inclui o download da base na primeira execução.
                "train_seconds": round(sum(h["seconds"] for h in result.history), 1),
            }
            if task == "ner":
                row["parameters_millions"] = round(
                    sum(p.numel() for p in result.model.parameters()) / 1e6, 1
                )
                row["cpu_latency"] = _cpu_latency(
                    result, task, [e.text for e in ner_validation[:300]]
                )
            else:
                row["cpu_latency_classifier"] = _cpu_latency(result, task, msg_validation[:300])
            del result
            gc.collect()
            torch.cuda.empty_cache()
        log(json.dumps(row, ensure_ascii=False))
        results.append(row)
    return results


def _cpu_latency(result: TrainResult, task: str, items: Sequence[Any]) -> dict[str, float]:
    model, tokenizer = result.model.to("cpu"), result.tokenizer

    def predict(batch: Sequence[Any]) -> Any:
        if task == "ner":
            return predict_ner(model, tokenizer, batch, 128)
        return predict_classifier(model, tokenizer, batch, 128)

    return latency(predict, items)


def render(results: Sequence[dict[str, Any]], *, dataset_version: str, epochs: int) -> str:
    lines = [
        "# Comparação de encoders",
        "",
        f"Dataset `{dataset_version}`, {epochs} época(s) por tarefa, mesma semente. Validação:",
        "NER = F1 micro exato (tipo e fronteiras); classificador = F1 macro com limiar calibrado.",
        "Latência: PyTorch fp32 em CPU, uma mensagem por vez (o modelo final roda em ONNX int8,",
        "bem mais rápido; aqui vale a comparação entre eles).",
        "",
        "| Encoder | Parâmetros (mi) | NER F1 | Classificador F1 macro | CPU p50 (ms) | Épocas NER + classificador (s) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        lines.append(
            f"| `{row['base_model']}` | {row['parameters_millions']} | {row['ner']['validation_score']:.4f} | "
            f"{row['classifier']['validation_score']:.4f} | {row['cpu_latency']['p50_ms']} | "
            f"{row['ner']['train_seconds'] + row['classifier']['train_seconds']:.0f} |"
        )
    return "\n".join(lines) + "\n"


def write(
    results: Sequence[dict[str, Any]], folder: Path, *, dataset_version: str, epochs: int
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"dataset_version": dataset_version, "epochs": epochs, "results": list(results)}
    (folder / "encoders.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (folder / "encoders.md").write_text(
        render(results, dataset_version=dataset_version, epochs=epochs),
        encoding="utf-8",
        newline="\n",
    )
