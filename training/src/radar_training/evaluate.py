"""Avaliação do modelo exportado (ONNX int8, pelo runtime de produção) contra os baselines.

Conjuntos: ``test`` (famílias de template que o treino nunca viu) e ``desafio`` (casos difíceis
escritos à mão: negação, citação, ironia, dado pessoal disfarçado). O ``test`` é sintético como o
treino, então mede generalização entre templates, não entre "mundos"; o desafio é pequeno.
Os dois números aparecem juntos, de propósito.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from radar.analysis.models import MessageInput
from radar.privacy.detector import PiiDetector
from radar.taxonomy import CLASSIFIER_LABELS, CUSTOMER_LABELS, PII_TYPES, SELLER_LABELS, SenderRole
from radar_training.baselines import (
    TfidfBaseline,
    llm_classifier,
    llm_ner,
    regex_ner,
    rules_classifier,
)
from radar_training.dataset import MessageExample, load_messages, load_ner
from radar_training.export import (
    FP32,
    INT8,
    agreement,
    latency,
    max_abs_diff,
    runtime_with,
    size_mb,
)
from radar_training.metrics import (
    Entity,
    apply_thresholds,
    label_confusion,
    mask_coverage,
    multilabel_report,
    ner_confusion,
    span_report,
    tune_thresholds,
)

EVAL_SPLITS = ("test", "desafio")
_NOW = datetime(2025, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------- NER
def _entities(spans: Sequence[Sequence[Any]]) -> list[list[Entity]]:
    return [[(s.type.value, s.start, s.end) for s in row] for row in spans]


def _ner_block(
    gold: list[list[Entity]], predicted: list[list[Entity]], *, confusion: bool = False
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "exato": span_report(gold, predicted, PII_TYPES).as_dict(),
        "mascara": mask_coverage(gold, predicted, PII_TYPES),
    }
    if confusion:
        block["confusao"] = ner_confusion(gold, predicted, PII_TYPES)
    return block


def evaluate_ner(
    model_dir: Path,
    dataset_dir: Path,
    *,
    llm_router: Any = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    # "O modelo" é o arquivo que o manifesto manda o runtime carregar (o quantizado aprovado).
    model = runtime_with(model_dir, None, "ner")
    reference = runtime_with(model_dir, FP32, "ner")
    detector = PiiDetector(ner=model)
    result: dict[str, Any] = {"splits": {}}
    for split in EVAL_SPLITS:
        examples = load_ner(dataset_dir, split)
        texts = [e.text for e in examples]
        gold = [list(e.entities) for e in examples]
        log(f"NER {split}: {len(texts)} mensagens")
        entry = {
            "mensagens": len(texts),
            "entidades": sum(len(g) for g in gold),
            "modelo": _ner_block(gold, _entities(model.predict(texts)), confusion=True),
            "regex": _ner_block(gold, regex_ner(texts)),
            # O que roda em produção: regex + validadores + modelo, trechos sobrepostos unidos.
            "regex_e_modelo": _ner_block(gold, _entities([detector.detect(t) for t in texts])),
        }
        if llm_router is not None:
            entry["llm_zero_shot"] = _ner_block(gold, llm_ner(texts, llm_router))
        result["splits"][split] = entry
    validation = [e.text for e in load_ner(dataset_dir, "validation")]
    result["paridade"] = _ner_parity(model_dir, model, reference, validation[:2000])
    result["latencia"] = {
        "int8": latency(model.predict, validation[:300]),
        "fp32": latency(reference.predict, validation[:300]),
    }
    result["tamanho_mb"] = {"int8": size_mb(model_dir / INT8), "fp32": size_mb(model_dir / FP32)}
    return result


def _ner_parity(
    model_dir: Path, model: Any, reference: Any, texts: Sequence[str]
) -> dict[str, Any]:
    fp32 = _entities(reference.predict(texts))
    int8 = _entities(model.predict(texts))
    parity: dict[str, Any] = {"mensagens": len(texts), "onnx_fp32_x_int8": agreement(fp32, int8)}
    torch_predictions = _torch_ner(model_dir, texts)
    if torch_predictions is not None:
        parity["pytorch_x_onnx_fp32"] = agreement(torch_predictions, fp32)
        parity["pytorch_x_onnx_int8"] = agreement(torch_predictions, int8)
    return parity


def _torch_ner(model_dir: Path, texts: Sequence[str]) -> list[list[Entity]] | None:
    if not (model_dir / "config.json").is_file():
        return None
    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        from radar_training.train import predict_ner
    except ImportError:
        return None
    # Na CPU e em fp32: na GPU o treino usa bf16, o que misturaria precisão com exportação.
    model = AutoModelForTokenClassification.from_pretrained(model_dir).to("cpu")
    return predict_ner(model, AutoTokenizer.from_pretrained(model_dir), texts, 128)


# ---------------------------------------------------------------- classificador
def _messages(examples: Sequence[MessageExample]) -> list[MessageInput]:
    return [MessageInput(i, e.sender, e.text, _NOW) for i, e in enumerate(examples)]


def _probabilities(model: Any, examples: Sequence[MessageExample]) -> NDArray[np.float32]:
    rows = model.predict(_messages(examples))
    return np.array(
        [[row.get(label, 0.0) for label in CLASSIFIER_LABELS] for row in rows], dtype=np.float32
    )


def allowed(labels: set[str], sender: SenderRole) -> set[str]:
    """Como a análise faz: rótulo de vendedor só em mensagem do vendedor, e vice-versa."""
    return labels & (SELLER_LABELS if sender is SenderRole.VENDEDOR else CUSTOMER_LABELS)


def calibrate(
    model_dir: Path, dataset_dir: Path, *, min_precision: float = 0.0
) -> dict[str, float]:
    """Limiar por rótulo calibrado no modelo **exportado** (o do manifesto) e na validação.

    Conta como a análise conta: rótulo de vendedor só em mensagem do vendedor, e o de cliente,
    na do cliente. Com ``min_precision``, o rótulo que não é confiável o bastante fica desligado.
    """
    examples = load_messages(dataset_dir, "validation")
    probabilities = _probabilities(runtime_with(model_dir, None, "classifier"), examples)
    relevant = np.array(
        [
            [label in allowed({label}, example.sender) for label in CLASSIFIER_LABELS]
            for example in examples
        ]
    )
    return tune_thresholds(
        [e.labels for e in examples],
        np.where(relevant, probabilities, 0.0).astype(np.float32),
        CLASSIFIER_LABELS,
        min_precision=min_precision,
    )


def quantization_score(
    model_dir: Path, dataset_dir: Path, task: str, *, limit: int = 2500
) -> Callable[[str], float]:
    """Mede um arquivo ONNX da pasta na validação, pelo runtime de produção.

    É a régua da quantização: F1 micro exato para o NER e F1 macro (com limiares calibrados no
    próprio arquivo) para o classificador, as mesmas métricas que escolhem a melhor época.
    """
    if task == "ner":
        ner_examples = load_ner(dataset_dir, "validation")[:limit]
        texts = [e.text for e in ner_examples]
        gold_spans = [list(e.entities) for e in ner_examples]

        def score_ner(onnx_file: str) -> float:
            model = runtime_with(model_dir, onnx_file, "ner")
            report = span_report(gold_spans, _entities(model.predict(texts)), PII_TYPES)
            return float(report.micro.f1)

        return score_ner

    examples = load_messages(dataset_dir, "validation")[:limit]
    gold_labels = [set(e.labels) for e in examples]

    def score_classifier(onnx_file: str) -> float:
        probabilities = _probabilities(runtime_with(model_dir, onnx_file, "classifier"), examples)
        thresholds = tune_thresholds([e.labels for e in examples], probabilities, CLASSIFIER_LABELS)
        predicted = _decide(probabilities, examples, thresholds)
        return float(multilabel_report(gold_labels, predicted, CLASSIFIER_LABELS).macro_f1)

    return score_classifier


def _cls_block(
    gold: list[set[str]], predicted: list[set[str]], *, confusion: bool = False
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "metricas": multilabel_report(gold, predicted, CLASSIFIER_LABELS).as_dict()
    }
    if confusion:
        block["confusao"] = label_confusion(gold, predicted, CLASSIFIER_LABELS)
    return block


def evaluate_classifier(
    model_dir: Path,
    dataset_dir: Path,
    *,
    llm_router: Any = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    model = runtime_with(model_dir, None, "classifier")
    reference = runtime_with(model_dir, FP32, "classifier")
    thresholds = model.thresholds
    validation = load_messages(dataset_dir, "validation")
    tfidf = _fit_tfidf(dataset_dir, validation, log)

    result: dict[str, Any] = {"splits": {}, "limiares": thresholds}
    for split in EVAL_SPLITS:
        examples = load_messages(dataset_dir, split)
        gold = [set(e.labels) for e in examples]
        log(f"Classificador {split}: {len(examples)} mensagens")
        predicted = _decide(_probabilities(model, examples), examples, thresholds)
        rules = rules_classifier(examples)
        entry = {
            "mensagens": len(examples),
            "modelo": _cls_block(gold, predicted, confusion=True),
            "regras": _cls_block(gold, rules),
            # O que a análise faz: regras e modelo somam rótulos.
            "regras_e_modelo": _cls_block(
                gold, [a | b for a, b in zip(rules, predicted, strict=True)]
            ),
        }
        if tfidf is not None:
            baseline, baseline_thresholds = tfidf
            entry["tfidf"] = _cls_block(
                gold, _decide(baseline.predict_proba(examples), examples, baseline_thresholds)
            )
        if llm_router is not None:
            entry["llm_zero_shot"] = _cls_block(
                gold,
                [
                    allowed(p, e.sender)
                    for p, e in zip(llm_classifier(examples, llm_router), examples, strict=True)
                ],
            )
        result["splits"][split] = entry
    result["paridade"] = _cls_parity(model_dir, model, reference, validation[:2000], thresholds)
    sample = validation[:300]
    result["latencia"] = {
        "int8": latency(lambda batch: model.predict(_messages(batch)), sample),
        "fp32": latency(lambda batch: reference.predict(_messages(batch)), sample),
    }
    result["tamanho_mb"] = {"int8": size_mb(model_dir / INT8), "fp32": size_mb(model_dir / FP32)}
    return result


def _decide(
    probabilities: NDArray[np.float32],
    examples: Sequence[MessageExample],
    thresholds: dict[str, float],
) -> list[set[str]]:
    decided = apply_thresholds(probabilities, CLASSIFIER_LABELS, thresholds)
    return [allowed(p, e.sender) for p, e in zip(decided, examples, strict=True)]


def _fit_tfidf(
    dataset_dir: Path, validation: Sequence[MessageExample], log: Callable[[str], None]
) -> tuple[TfidfBaseline, dict[str, float]] | None:
    try:
        import sklearn  # noqa: F401
    except ImportError:
        log("scikit-learn ausente (extra train): o baseline TF-IDF fica de fora")
        return None
    log("TF-IDF: treinando o baseline")
    baseline = TfidfBaseline().fit(load_messages(dataset_dir, "train"))
    thresholds = tune_thresholds(
        [e.labels for e in validation], baseline.predict_proba(validation), CLASSIFIER_LABELS
    )
    return baseline, thresholds


def _cls_parity(
    model_dir: Path,
    model: Any,
    reference: Any,
    examples: Sequence[MessageExample],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    fp32 = _probabilities(reference, examples)
    int8 = _probabilities(model, examples)

    def decide(p: NDArray[np.float32]) -> list[set[str]]:
        return apply_thresholds(p, CLASSIFIER_LABELS, thresholds)

    parity: dict[str, Any] = {
        "mensagens": len(examples),
        "onnx_fp32_x_int8_decisoes": agreement(decide(fp32), decide(int8)),
        "onnx_fp32_x_int8_dif_max_prob": round(max_abs_diff(fp32, int8), 4),
    }
    torch_probabilities = _torch_classifier(model_dir, examples)
    if torch_probabilities is not None:
        parity["pytorch_x_onnx_fp32_dif_max_prob"] = round(
            max_abs_diff(torch_probabilities, fp32), 5
        )
        parity["pytorch_x_onnx_int8_decisoes"] = agreement(
            decide(torch_probabilities), decide(int8)
        )
    return parity


def _torch_classifier(
    model_dir: Path, examples: Sequence[MessageExample]
) -> NDArray[np.float32] | None:
    if not (model_dir / "config.json").is_file():
        return None
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        from radar_training.train import predict_classifier
    except ImportError:
        return None
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).to("cpu")
    return predict_classifier(model, AutoTokenizer.from_pretrained(model_dir), examples, 128)
