"""Modelos ONNX minúsculos e determinísticos, para testar o runtime e a avaliação sem PyTorch.

Cada token do vocabulário tem uma linha fixa de logits (uma tabela ``Gather``): o NER rotula
token a token ("joana" → ``B-NOME_PESSOA``, "silva" → ``I-NOME_PESSOA``) e o classificador pega
o máximo da frase ("pix" → pagamento fora do canal, "caro" → objeção de preço). O teste exercita o
runtime real (tokenizador, janelas, decodificação, limiares) com respostas previsíveis.

Precisa do pacote ``onnx`` (grupo ``dev``); só os testes importam este módulo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from radar.ml.ner import NER_LABELS

VOCAB = [
    "[PAD]", "[UNK]", "[CLS]", "[SEP]",
    "vendedor", "cliente", "meu", "nome", "e", "joana", "silva", "oi", "tudo", "bem",
    "pode", "pagar", "no", "pix", "achei", "caro", "fala", "com", "a", ",", ".",
]  # fmt: skip
IDS = {token: i for i, token in enumerate(VOCAB)}

TINY_CLASSIFIER_LABELS = ["pagamento_fora_canal", "objecao_preco", "sinal_compra"]


def build_tokenizer(path: Path) -> None:
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

    tokenizer = Tokenizer(models.WordLevel(IDS, unk_token="[UNK]"))  # noqa: S106 (token de vocabulário)
    tokenizer.normalizer = normalizers.Sequence(
        [normalizers.NFD(), normalizers.StripAccents(), normalizers.Lowercase()]
    )
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        pair="[CLS] $A [SEP] $B:1 [SEP]:1",
        special_tokens=[("[CLS]", IDS["[CLS]"]), ("[SEP]", IDS["[SEP]"])],
    )
    tokenizer.save(str(path))


def build_onnx(path: Path, table: NDArray[Any], *, pooled: bool) -> None:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    inputs = [
        helper.make_tensor_value_info(name, TensorProto.INT64, ["batch", "seq"])
        for name in ("input_ids", "attention_mask", "token_type_ids")
    ]
    nodes = [helper.make_node("Gather", ["table", "input_ids"], ["per_token"], axis=0)]
    if pooled:
        nodes.append(helper.make_node("ReduceMax", ["per_token"], ["logits"], axes=[1], keepdims=0))
        shape: list[str | int] = ["batch", int(table.shape[1])]
    else:
        nodes.append(helper.make_node("Identity", ["per_token"], ["logits"]))
        shape = ["batch", "seq", int(table.shape[1])]
    output = helper.make_tensor_value_info("logits", TensorProto.FLOAT, shape)
    graph = helper.make_graph(
        nodes,
        "radar-teste",
        inputs,
        [output],
        [numpy_helper.from_array(table.astype(np.float32), "table")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(path))


def _bundle(
    folder: Path, table: NDArray[Any], manifest: dict[str, object], *, pooled: bool
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    build_tokenizer(folder / "tokenizer.json")
    # fp32 e int8 iguais: o suficiente para testar o caminho de avaliação e paridade.
    for name in ("model.onnx", "model_quantized.onnx"):
        build_onnx(folder / "onnx" / name, table, pooled=pooled)
    (folder / "radar_model.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def tiny_ner_model(folder: Path, **overrides: object) -> Path:
    labels = list(NER_LABELS)
    table = np.zeros((len(VOCAB), len(labels)))
    table[:, labels.index("O")] = 5.0
    table[IDS["joana"], labels.index("B-NOME_PESSOA")] = 10.0
    table[IDS["silva"], labels.index("I-NOME_PESSOA")] = 10.0
    manifest: dict[str, object] = {
        "name": "ner-teste", "task": "ner", "version": "1.0", "labels": labels,
        "max_length": 32, "stride": 4,
    }  # fmt: skip
    manifest.update(overrides)
    return _bundle(folder, table, manifest, pooled=False)


def tiny_classifier_model(folder: Path, **overrides: object) -> Path:
    table = np.full((len(VOCAB), len(TINY_CLASSIFIER_LABELS)), -6.0)
    table[IDS["pix"], 0] = 3.0  # probabilidade ~0,95
    table[IDS["caro"], 1] = 0.4  # ~0,60: passa no limiar 0,5, não no 0,7
    manifest: dict[str, object] = {
        "name": "classificador-teste", "task": "classifier", "version": "1.0",
        "labels": TINY_CLASSIFIER_LABELS, "max_length": 32,
        "thresholds": dict.fromkeys(TINY_CLASSIFIER_LABELS, 0.5),
    }  # fmt: skip
    manifest.update(overrides)
    return _bundle(folder, table, manifest, pooled=True)
