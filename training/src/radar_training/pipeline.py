"""Do dataset ao modelo publicável: treinar, exportar, calibrar, avaliar, relatar.

Pasta do modelo (``models/<nome>/``), igual ao repositório no Hub::

    config.json, model.safetensors, tokenizer*.json…  pesos do Transformers
    onnx/model.onnx, onnx/model_quantized.onnx      ONNX fp32 e int8
    radar_model.json                                 manifesto do runtime
    training.json                                    configuração, histórico e hardware do treino
    metrics.json                                     relatório completo (base do model card)
    README.md                                        model card
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar_training.config import TrainConfig
from radar_training.dataset import dataset_manifest, load_messages, load_ner
from radar_training.export import FP32, INT8, export_onnx, quantize, write_manifest
from radar_training.report import render_card, render_report

DATASET_NAME = "radar-vendas-conversas-sinteticas"


def _hardware() -> str:
    import torch

    return torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"


def train(
    config: TrainConfig, dataset_dir: Path, folder: Path, log: Callable[[str], None]
) -> dict[str, Any]:
    import torch
    import transformers

    from radar_training.train import save_pretrained, train_classifier, train_ner

    if config.task == "ner":
        result = train_ner(
            config, load_ner(dataset_dir, "train"), load_ner(dataset_dir, "validation"), log
        )
    else:
        result = train_classifier(
            config,
            load_messages(dataset_dir, "train"),
            load_messages(dataset_dir, "validation"),
            log,
        )
    if folder.exists():
        shutil.rmtree(folder)
    save_pretrained(result, folder)
    training = {
        "config": config.model_dump(),
        "best_epoch": result.best_epoch,
        "best_score": round(result.best_score, 5),
        "history": result.history,
        "seconds": round(result.seconds, 1),
        "hardware": _hardware(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
    }
    (folder / "training.json").write_text(
        json.dumps(training, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return training


def export(
    config: TrainConfig, dataset_dir: Path, folder: Path, log: Callable[[str], None]
) -> None:
    from transformers import AutoTokenizer

    from radar_training.evaluate import calibrate, quantization_score

    log("Exportando para ONNX")
    export_onnx(folder, config.task)
    version = dataset_manifest(dataset_dir)["version"]
    pad = AutoTokenizer.from_pretrained(folder).pad_token_id or 0
    # O manifesto vem antes da quantização: o runtime de produção precisa dele para medir.
    write_manifest(folder, config, dataset_version=version, pad_token_id=pad, thresholds={})
    log("Quantizando e conferindo a qualidade na validação")
    quantization = quantize(folder, quantization_score(folder, dataset_dir, config.task), log=log)
    onnx_file = INT8 if quantization["aprovado"] else FP32
    if not quantization["aprovado"]:
        log(
            "ATENÇÃO: nenhuma quantização ficou dentro da tolerância; o runtime vai usar o fp32 "
            "(maior e mais lento, mas com a qualidade do treino)."
        )
    thresholds: dict[str, float] = {}
    if config.task == "classifier":
        write_manifest(
            folder,
            config,
            dataset_version=version,
            pad_token_id=pad,
            thresholds={},
            onnx_file=onnx_file,
        )
        log("Calibrando os limiares no modelo que vai para produção")
        thresholds = calibrate(folder, dataset_dir, min_precision=config.min_precision)
        off = sorted(label for label, value in thresholds.items() if value > 1.0)
        if off:
            log(
                f"Rótulos desligados (precisão abaixo de {config.min_precision} na validação): "
                + ", ".join(off)
            )
    write_manifest(
        folder,
        config,
        dataset_version=version,
        pad_token_id=pad,
        thresholds=thresholds,
        onnx_file=onnx_file,
    )
    training_file = folder / "training.json"
    if training_file.is_file():
        training = json.loads(training_file.read_text(encoding="utf-8"))
        training["quantizacao"] = quantization
        # Com --skip-train a configuração pode ter mudado depois do treino (ex.: min_precision).
        training["config"] = config.model_dump()
        training_file.write_text(
            json.dumps(training, indent=2) + "\n", encoding="utf-8", newline="\n"
        )


def evaluate(
    folder: Path,
    dataset_dir: Path,
    reports_dir: Path,
    *,
    namespace: str,
    llm_router: Any = None,
    log: Callable[[str], None],
) -> dict[str, Any]:
    from radar.ml.bundle import MANIFEST, ModelManifest
    from radar_training.evaluate import evaluate_classifier, evaluate_ner

    manifest = ModelManifest.model_validate_json(
        (folder / MANIFEST).read_text(encoding="utf-8")
    ).model_dump()
    training = json.loads((folder / "training.json").read_text(encoding="utf-8"))
    run = evaluate_ner if manifest["task"] == "ner" else evaluate_classifier
    report = {
        "modelo": {
            k: manifest[k] for k in ("name", "version", "task", "base_model", "dataset_version")
        },
        "treino": training,
        "avaliacao": run(folder, dataset_dir, llm_router=llm_router, log=log),
        "gerado_em": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    (folder / "metrics.json").write_text(text, encoding="utf-8", newline="\n")
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{manifest['name']}.json").write_text(text, encoding="utf-8", newline="\n")
    (reports_dir / f"{manifest['name']}.md").write_text(
        render_report(report), encoding="utf-8", newline="\n"
    )
    (folder / "README.md").write_text(
        render_card(
            report,
            repo_id=f"{namespace}/{manifest['name']}",
            dataset_id=f"{namespace}/{DATASET_NAME}",
        ),
        encoding="utf-8",
        newline="\n",
    )
    return report
