"""Ajuste fino dos encoders (PyTorch). Precisa do extra ``train``.

Laço de treino próprio (AdamW, aquecimento linear, bf16 na GPU, recorte de gradiente, parada
antecipada pela validação), em vez do ``Trainer``: menos dependências e controle total da semente
e da métrica usada para escolher a melhor época.

O NER rotula todos os pedaços de cada palavra (não só o primeiro) e é decodificado pelas mesmas
funções do runtime (``radar.ml.ner``). O classificador recebe o par (papel, texto mascarado).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from radar.ml.classifier import classifier_pair
from radar.ml.ner import NER_LABELS, decode_bio, merge_overlapping, token_labels
from radar.taxonomy import CLASSIFIER_LABELS, PII_TYPES
from radar_training.config import TrainConfig
from radar_training.dataset import MessageExample, NerExample
from radar_training.metrics import (
    Entity,
    apply_thresholds,
    multilabel_report,
    span_report,
    tune_thresholds,
)

IGNORE = -100


@dataclass(slots=True)
class TrainResult:
    model: Any
    tokenizer: Any
    best_epoch: int
    best_score: float
    history: list[dict[str, float]] = field(default_factory=list)
    seconds: float = 0.0
    thresholds: dict[str, float] = field(default_factory=dict)


def device() -> Any:
    import torch

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def set_seed(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False


# ---------------------------------------------------------------- features
def ner_features(
    examples: Sequence[NerExample], tokenizer: Any, max_length: int
) -> list[dict[str, list[int]]]:
    features = []
    for example in examples:
        encoded = tokenizer(
            example.text,
            truncation=True,
            max_length=max_length,
            return_offsets_mapping=True,
            return_special_tokens_mask=True,
        )
        labels = token_labels(
            encoded["offset_mapping"], encoded["special_tokens_mask"], example.entities
        )
        feature = {
            k: encoded[k] for k in ("input_ids", "attention_mask", "token_type_ids") if k in encoded
        }
        feature["labels"] = [NER_LABELS.index(label) if label else IGNORE for label in labels]
        features.append(feature)
    return features


def classifier_features(
    examples: Sequence[MessageExample], tokenizer: Any, max_length: int
) -> list[dict[str, Any]]:
    features = []
    for example in examples:
        sender, text = classifier_pair(example.sender, example.text)
        encoded = tokenizer(sender, text, truncation="only_second", max_length=max_length)
        feature: dict[str, Any] = {
            k: encoded[k] for k in ("input_ids", "attention_mask", "token_type_ids") if k in encoded
        }
        feature["labels"] = [float(label in example.labels) for label in CLASSIFIER_LABELS]
        features.append(feature)
    return features


def collate(
    pad_id: int, *, token_labels_padded: bool
) -> Callable[[list[dict[str, Any]]], dict[str, Any]]:
    import torch

    def _collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
        width = max(len(item["input_ids"]) for item in batch)
        out: dict[str, Any] = {}
        for key, fill in (("input_ids", pad_id), ("attention_mask", 0), ("token_type_ids", 0)):
            if key in batch[0]:
                out[key] = torch.tensor(
                    [item[key] + [fill] * (width - len(item[key])) for item in batch]
                )
        if token_labels_padded:
            out["labels"] = torch.tensor(
                [item["labels"] + [IGNORE] * (width - len(item["labels"])) for item in batch]
            )
        else:
            out["labels"] = torch.tensor([item["labels"] for item in batch], dtype=torch.float32)
        return out

    return _collate


# ---------------------------------------------------------------- predição (PyTorch)
def _batches[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def predict_ner(
    model: Any, tokenizer: Any, texts: Sequence[str], max_length: int, batch_size: int = 64
) -> list[list[Entity]]:
    import torch

    model.eval()
    result: list[list[Entity]] = []
    with torch.inference_mode():
        for batch in _batches(texts, batch_size):
            encoded = tokenizer(
                list(batch),
                truncation=True,
                max_length=max_length,
                padding=True,
                return_offsets_mapping=True,
                return_special_tokens_mask=True,
                return_tensors="pt",
            )
            offsets = encoded.pop("offset_mapping").tolist()
            special = encoded.pop("special_tokens_mask").tolist()
            inputs = {k: v.to(model.device) for k, v in encoded.items()}
            with _autocast(model.device):
                logits = model(**inputs).logits
            probabilities = logits.float().softmax(-1).cpu().numpy()
            lengths = encoded["attention_mask"].sum(dim=1).tolist()
            for text, off, spe, prob, size in zip(
                batch, offsets, special, probabilities, lengths, strict=True
            ):
                spans = decode_bio(text, off[:size], spe[:size], prob[:size], NER_LABELS)
                result.append([(s.type, s.start, s.end) for s in merge_overlapping(spans)])
    return result


def predict_classifier(
    model: Any,
    tokenizer: Any,
    examples: Sequence[MessageExample],
    max_length: int,
    batch_size: int = 64,
) -> NDArray[np.float32]:
    import torch

    model.eval()
    rows: list[NDArray[np.float32]] = []
    with torch.inference_mode():
        for batch in _batches(examples, batch_size):
            pairs = [classifier_pair(e.sender, e.text) for e in batch]
            encoded = tokenizer(
                [p[0] for p in pairs],
                [p[1] for p in pairs],
                truncation="only_second",
                max_length=max_length,
                padding=True,
                return_tensors="pt",
            )
            inputs = {k: v.to(model.device) for k, v in encoded.items()}
            with _autocast(model.device):
                logits = model(**inputs).logits
            rows.append(logits.float().sigmoid().cpu().numpy())
    return np.concatenate(rows) if rows else np.zeros((0, len(CLASSIFIER_LABELS)), dtype=np.float32)


def _autocast(target: Any) -> Any:
    import contextlib

    import torch

    if target.type == "cuda" and torch.cuda.is_bf16_supported():
        return torch.autocast("cuda", dtype=torch.bfloat16)
    return contextlib.nullcontext()


# ---------------------------------------------------------------- laço de treino
def _fit(
    config: TrainConfig,
    model: Any,
    features: list[dict[str, Any]],
    collate_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
    evaluate: Callable[[Any], tuple[float, dict[str, float]]],
    log: Callable[[str], None],
) -> tuple[Any, int, float, list[dict[str, float]]]:
    import torch
    from torch.utils.data import DataLoader
    from transformers import get_linear_schedule_with_warmup

    generator = torch.Generator().manual_seed(config.seed)
    loader = DataLoader(
        features,
        batch_size=config.batch_size,
        shuffle=True,
        collate_fn=collate_fn,
        generator=generator,
    )
    no_decay = ("bias", "LayerNorm.weight", "norm.weight")
    groups = [
        {
            "params": [p for n, p in model.named_parameters() if not n.endswith(no_decay)],
            "weight_decay": config.weight_decay,
        },
        {
            "params": [p for n, p in model.named_parameters() if n.endswith(no_decay)],
            "weight_decay": 0.0,
        },
    ]
    optimizer = torch.optim.AdamW(groups, lr=config.learning_rate)
    total = len(loader) * config.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, int(total * config.warmup_ratio), total)

    best_state, best_epoch, best_score, stale = None, 0, -1.0, 0
    history: list[dict[str, float]] = []
    for epoch in range(1, config.epochs + 1):
        model.train()
        started, running = time.perf_counter(), 0.0
        for step, batch in enumerate(loader, start=1):
            batch = {k: v.to(model.device) for k, v in batch.items()}
            with _autocast(model.device):
                loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            running += float(loss)
            if step % 200 == 0:
                log(f"  época {epoch} passo {step}/{len(loader)} perda {running / step:.4f}")
        score, extra = evaluate(model)
        entry = {
            "epoch": epoch,
            "loss": round(running / len(loader), 5),
            "score": round(score, 5),
            **extra,
        }
        entry["seconds"] = round(time.perf_counter() - started, 1)
        history.append(entry)
        log(
            f"época {epoch}: perda {entry['loss']:.4f} validação {score:.4f} ({entry['seconds']} s)"
        )
        if score > best_score:
            best_state = {k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()}
            best_epoch, best_score, stale = epoch, score, 0
        else:
            stale += 1
            if stale >= config.patience:
                log(f"parou na época {epoch}: {stale} sem melhora")
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, best_epoch, best_score, history


def train_ner(
    config: TrainConfig,
    train: Sequence[NerExample],
    validation: Sequence[NerExample],
    log: Callable[[str], None] = print,
) -> TrainResult:
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    set_seed(config.seed)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    model = AutoModelForTokenClassification.from_pretrained(
        config.base_model,
        num_labels=len(NER_LABELS),
        id2label=dict(enumerate(NER_LABELS)),
        label2id={label: i for i, label in enumerate(NER_LABELS)},
    ).to(device())
    features = ner_features(train, tokenizer, config.max_length)
    gold = [list(e.entities) for e in validation]
    texts = [e.text for e in validation]

    def evaluate(current: Any) -> tuple[float, dict[str, float]]:
        report = span_report(
            gold, predict_ner(current, tokenizer, texts, config.max_length), PII_TYPES
        )
        return report.micro.f1, {"macro_f1": round(report.macro_f1, 5)}

    model, epoch, score, history = _fit(
        config,
        model,
        features,
        collate(tokenizer.pad_token_id, token_labels_padded=True),
        evaluate,
        log,
    )
    return TrainResult(model, tokenizer, epoch, score, history, time.perf_counter() - started)


def train_classifier(
    config: TrainConfig,
    train: Sequence[MessageExample],
    validation: Sequence[MessageExample],
    log: Callable[[str], None] = print,
) -> TrainResult:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    set_seed(config.seed)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    model = AutoModelForSequenceClassification.from_pretrained(
        config.base_model,
        num_labels=len(CLASSIFIER_LABELS),
        problem_type="multi_label_classification",
        id2label=dict(enumerate(CLASSIFIER_LABELS)),
        label2id={label: i for i, label in enumerate(CLASSIFIER_LABELS)},
    ).to(device())
    features = classifier_features(train, tokenizer, config.max_length)
    gold = [e.labels for e in validation]

    def evaluate(current: Any) -> tuple[float, dict[str, float]]:
        probabilities = predict_classifier(current, tokenizer, validation, config.max_length)
        thresholds = tune_thresholds(gold, probabilities, CLASSIFIER_LABELS)
        report = multilabel_report(
            gold, apply_thresholds(probabilities, CLASSIFIER_LABELS, thresholds), CLASSIFIER_LABELS
        )
        return report.macro_f1, {"micro_f1": round(report.micro.f1, 5)}

    model, epoch, score, history = _fit(
        config,
        model,
        features,
        collate(tokenizer.pad_token_id, token_labels_padded=False),
        evaluate,
        log,
    )
    probabilities = predict_classifier(model, tokenizer, validation, config.max_length)
    thresholds = tune_thresholds(gold, probabilities, CLASSIFIER_LABELS)
    return TrainResult(
        model, tokenizer, epoch, score, history, time.perf_counter() - started, thresholds
    )


def save_pretrained(result: TrainResult, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    result.model.save_pretrained(folder)
    result.tokenizer.save_pretrained(folder)
