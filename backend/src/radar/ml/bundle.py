"""Pasta de um modelo próprio: manifesto, tokenizador e ONNX.

A mesma estrutura serve para a pasta local (``models/<nome>/``) e para o repositório no Hugging
Face, então baixar é só copiar arquivos::

    radar_model.json          o manifesto abaixo
    tokenizer.json            tokenizador (biblioteca ``tokenizers``)
    onnx/model_quantized.onnx pesos em int8 para CPU (o runtime usa este)
    onnx/model.onnx           fp32 (referência)
    config.json, model.safetensors…  pesos do Transformers, para quem quiser ajustar

A inferência usa só ``onnxruntime`` e ``tokenizers``: nada de PyTorch em produção.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field

MANIFEST = "radar_model.json"


class ModelManifest(BaseModel):
    """O que o runtime precisa saber de um modelo, gravado pelo treino."""

    format: Literal[1] = 1
    name: str
    task: Literal["ner", "classifier"]
    version: str
    #: Rótulos na ordem das saídas do modelo (``O``, ``B-CPF``… ou os tipos do classificador).
    labels: list[str]
    max_length: int = Field(default=128, ge=8, le=4096)
    #: Sobreposição entre janelas de um texto longo (NER).
    stride: int = Field(default=32, ge=0)
    pad_token_id: int = 0
    #: Limiar por rótulo (classificador), calibrado na validação.
    thresholds: dict[str, float] = Field(default_factory=dict)
    onnx: str = "onnx/model_quantized.onnx"
    base_model: str = ""
    dataset_version: str = ""

    @property
    def tag(self) -> str:
        return f"{self.name}@{self.version}"


class ModelBundle:
    """Modelo carregado: manifesto, tokenizador e sessão do ONNX Runtime."""

    def __init__(self, path: Path, *, threads: int = 0, onnx_file: str | None = None) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.path = path
        self.manifest = ModelManifest.model_validate_json(
            (path / MANIFEST).read_text(encoding="utf-8")
        )
        self.tokenizer = Tokenizer.from_file(str(path / "tokenizer.json"))
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        if threads:
            options.intra_op_num_threads = threads
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(path / (onnx_file or self.manifest.onnx)),
            options,
            providers=["CPUExecutionProvider"],
        )
        self.input_names = {item.name for item in self.session.get_inputs()}

    def run(self, encodings: Sequence[Any]) -> NDArray[np.float32]:
        """Roda um lote de ``tokenizers.Encoding`` (com preenchimento) e devolve os logits."""
        width = max(len(e.ids) for e in encodings)
        shape = (len(encodings), width)
        ids = np.full(shape, self.manifest.pad_token_id, dtype=np.int64)
        attention = np.zeros(shape, dtype=np.int64)
        types = np.zeros(shape, dtype=np.int64)
        for row, encoding in enumerate(encodings):
            size = len(encoding.ids)
            ids[row, :size] = encoding.ids
            attention[row, :size] = 1
            types[row, :size] = encoding.type_ids
        feeds = {"input_ids": ids, "attention_mask": attention, "token_type_ids": types}
        outputs = self.session.run(None, {k: v for k, v in feeds.items() if k in self.input_names})
        return np.asarray(outputs[0], dtype=np.float32)


def softmax(logits: NDArray[np.float32]) -> NDArray[np.float32]:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return np.asarray(exp / exp.sum(axis=-1, keepdims=True), dtype=np.float32)


def sigmoid(logits: NDArray[np.float32]) -> NDArray[np.float32]:
    return np.asarray(1.0 / (1.0 + np.exp(-logits)), dtype=np.float32)
