"""Exportação para ONNX, quantização int8, paridade e latência em CPU.

A paridade compara o PyTorch com o ONNX **pelo runtime de produção** (``radar.ml``): o número
publicado é o do código que roda no Radar, não o de um caminho paralelo.
"""

from __future__ import annotations

import gc
import logging
import statistics
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from radar.ml.bundle import MANIFEST, ModelManifest
from radar.ml.ner import NER_LABELS
from radar.taxonomy import CLASSIFIER_LABELS
from radar_training.config import TrainConfig

FP32 = "onnx/model.onnx"
INT8 = "onnx/model_quantized.onnx"


def export_onnx(folder: Path, task: str) -> Path:
    """Exporta os pesos do Transformers em ``folder`` para ``folder/onnx/model.onnx`` (fp32)."""
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoModelForTokenClassification,
        AutoTokenizer,
    )

    auto = AutoModelForTokenClassification if task == "ner" else AutoModelForSequenceClassification
    model = auto.from_pretrained(folder).eval().to("cpu")
    tokenizer = AutoTokenizer.from_pretrained(folder)
    sample = tokenizer(
        ["Oi, tudo bem?", "Pode mandar a proposta pelo e-mail, por favor"],
        padding=True,
        return_tensors="pt",
    )
    names = [n for n in ("input_ids", "attention_mask", "token_type_ids") if n in sample]

    # Assinatura explícita: o torch.export precisa saber o nome de cada entrada.
    class WithTypes(torch.nn.Module):  # type: ignore[misc]  # torch é Any para o mypy
        def __init__(self, inner: Any) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, input_ids: Any, attention_mask: Any, token_type_ids: Any) -> Any:
            return self.inner(
                input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids
            ).logits

    class WithoutTypes(torch.nn.Module):  # type: ignore[misc]  # torch é Any para o mypy
        def __init__(self, inner: Any) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, input_ids: Any, attention_mask: Any) -> Any:
            return self.inner(input_ids=input_ids, attention_mask=attention_mask).logits

    wrapper = WithTypes(model) if "token_type_ids" in names else WithoutTypes(model)
    target = folder / FP32
    target.parent.mkdir(parents=True, exist_ok=True)
    dims = {0: torch.export.Dim.DYNAMIC, 1: torch.export.Dim.DYNAMIC}
    torch.onnx.export(
        wrapper,
        tuple(sample[n] for n in names),
        str(target),
        input_names=names,
        output_names=["logits"],
        dynamic_shapes=dict.fromkeys(names, dims),
        dynamo=True,
        external_data=False,
    )
    return target


#: Receitas de quantização dinâmica, da preferida para a de reserva.
#:
#: A receita "óbvia" (pesos int8 com sinal, uma escala por tensor, 8 bits cheios) derrubou o F1
#: do ``pii-ner-ptbr`` de 0,94 para 0,63 no teste, sem nenhum aviso. A causa provável é a
#: saturação da soma de 16 bits, que o ONNX Runtime recomenda evitar com ``reduce_range`` em CPUs
#: sem VNNI. Por canal e com a faixa reduzida a 7 bits o F1 ficou em 0,94; a de pesos sem sinal
#: fica de reserva. O resultado depende do modelo e da CPU, então nenhuma receita é aceita sem
#: passar pela validação (``quantize``).
QUANT_RECIPES: tuple[tuple[str, dict[str, bool]], ...] = (
    (
        "int8 por canal com faixa reduzida",
        {"signed": True, "per_channel": True, "reduce_range": True},
    ),
    ("uint8", {"signed": False, "per_channel": False, "reduce_range": False}),
)

#: Quanto a métrica do modelo quantizado pode ficar abaixo da do fp32 na validação.
QUANT_TOLERANCE = 0.01


def _quantize_to(
    clean: Path, target: Path, *, signed: bool, per_channel: bool, reduce_range: bool
) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.WARNING)  # o quantizador loga cada nó em INFO
    try:
        quantize_dynamic(
            str(clean),
            str(target),
            weight_type=QuantType.QInt8 if signed else QuantType.QUInt8,
            per_channel=per_channel,
            reduce_range=reduce_range,
        )
    finally:
        root.setLevel(level)


def quantize(
    folder: Path,
    score: Callable[[str], float] | None = None,
    *,
    tolerance: float = QUANT_TOLERANCE,
    log: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    """Quantização dinâmica (pesos em 8 bits): ~4x menor e mais rápido em CPU.

    ``score`` mede um arquivo ONNX da pasta na validação, pelo runtime de produção. Cada receita
    é medida contra o fp32 e a primeira que perde no máximo ``tolerance`` é a escolhida. Se
    nenhuma passar, o resultado vem com ``aprovado: False`` e quem chama deve servir o fp32: um
    modelo quantizado que erra mais do que o original não pode virar o padrão em silêncio.
    Sem ``score`` (testes), usa a primeira receita sem medir.
    """
    import tempfile

    import onnx

    # As anotações de forma intermediárias (value_info) do exportador dynamo às vezes divergem
    # da inferência de formas do ONNX e travam o quantizador; são opcionais e são refeitas.
    model = onnx.load(str(folder / FP32))
    model.graph.ClearField("value_info")
    target = folder / INT8
    reference = score(FP32) if score is not None else None
    attempts: list[dict[str, Any]] = []
    best: tuple[float, Path] | None = None
    candidates: list[Path] = []
    with tempfile.TemporaryDirectory() as scratch:
        clean = Path(scratch) / "model.onnx"
        onnx.save(model, str(clean))
        del model
        for index, (name, recipe) in enumerate(QUANT_RECIPES):
            candidate = target.with_name(f"candidato-{index}.onnx")
            candidates.append(candidate)
            _quantize_to(clean, candidate, **recipe)
            if score is None or reference is None:
                attempts.append({"receita": name})
                best = (0.0, candidate)
                break
            value = score(f"{target.parent.name}/{candidate.name}")
            attempts.append({"receita": name, "metrica": round(value, 5)})
            log(f"quantização '{name}': {value:.4f} (fp32: {reference:.4f})")
            if best is None or value > best[0]:
                best = (value, candidate)
            if value >= reference - tolerance:
                break
    if best is None:
        raise RuntimeError("nenhuma receita de quantização configurada")
    chosen = candidates.index(best[1])
    gc.collect()  # solta as sessões do ONNX Runtime antes de mexer nos arquivos (Windows)
    best[1].replace(target)
    for candidate in candidates:
        candidate.unlink(missing_ok=True)
    approved = reference is None or best[0] >= reference - tolerance
    result: dict[str, Any] = {
        "receita": QUANT_RECIPES[chosen][0],
        "aprovado": approved,
        "tolerancia": tolerance,
        "tentativas": attempts,
    }
    if reference is not None:
        result["metrica_fp32"] = round(reference, 5)
        result["metrica_quantizado"] = round(best[0], 5)
    return result


def write_manifest(
    folder: Path,
    config: TrainConfig,
    *,
    dataset_version: str,
    pad_token_id: int,
    thresholds: dict[str, float],
    onnx_file: str = INT8,
) -> ModelManifest:
    manifest = ModelManifest(
        name=config.name,
        task=config.task,
        version=config.version,
        labels=list(NER_LABELS if config.task == "ner" else CLASSIFIER_LABELS),
        max_length=config.max_length,
        stride=config.stride,
        pad_token_id=pad_token_id,
        thresholds=thresholds,
        onnx=onnx_file,
        base_model=config.base_model,
        dataset_version=dataset_version,
    )
    (folder / MANIFEST).write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def runtime_with(folder: Path, onnx_file: str | None, task: str) -> Any:
    """O runtime de produção apontado para um arquivo ONNX (``None`` = o do manifesto)."""
    from radar.ml.classifier import OnnxMessageClassifier
    from radar.ml.ner import OnnxPiiNer

    if task == "ner":
        return OnnxPiiNer(folder, onnx_file=onnx_file)
    return OnnxMessageClassifier(folder, onnx_file=onnx_file)


def latency(
    predict: Callable[[Sequence[Any]], Any], items: Sequence[Any], *, runs: int = 60
) -> dict[str, float]:
    """Milissegundos por mensagem isolada (p50, p95) e mensagens por segundo em lotes de 32."""
    for item in items[:5]:
        predict([item])
    single = []
    for i in range(runs):
        started = time.perf_counter()
        predict([items[i % len(items)]])
        single.append((time.perf_counter() - started) * 1000)
    batch = list(items[:256])
    started = time.perf_counter()
    for begin in range(0, len(batch), 32):
        predict(batch[begin : begin + 32])
    elapsed = time.perf_counter() - started
    single.sort()
    return {
        "p50_ms": round(statistics.median(single), 2),
        "p95_ms": round(single[int(len(single) * 0.95) - 1], 2),
        "messages_per_second": round(len(batch) / elapsed, 1),
    }


def size_mb(path: Path) -> float:
    return round(path.stat().st_size / 1_000_000, 1)


def agreement(a: Sequence[Any], b: Sequence[Any]) -> float:
    """Fração de exemplos com a mesma resposta (conjunto de trechos ou de rótulos)."""
    same = sum(set(x) == set(y) for x, y in zip(a, b, strict=True))
    return round(same / len(a), 4) if a else 1.0


def max_abs_diff(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.max(np.abs(x - y))) if x.size else 0.0
