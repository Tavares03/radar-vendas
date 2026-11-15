"""Classificador multirrótulo de mensagens de venda (``sales-intent-ptbr``) em ONNX.

Entrada: o par (quem escreveu, texto **mascarado**), o mesmo que a análise enxerga. O treino usa
``classifier_pair`` daqui para montar a entrada do mesmo jeito.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from radar.analysis.models import MessageInput
from radar.ml.bundle import ModelBundle, sigmoid
from radar.taxonomy import CLASSIFIER_LABELS, SenderRole


def classifier_pair(sender: SenderRole | str, text: str) -> tuple[str, str]:
    """A entrada do modelo: o papel de quem escreveu e o texto."""
    return (SenderRole(sender).value, text)


class OnnxMessageClassifier:
    """Implementa ``radar.analysis.models.MessageClassifier`` com um modelo ONNX."""

    def __init__(
        self, path: Path, *, threads: int = 0, batch_size: int = 32, onnx_file: str | None = None
    ) -> None:
        self.bundle = ModelBundle(path, threads=threads, onnx_file=onnx_file)
        manifest = self.bundle.manifest
        if manifest.task != "classifier":
            raise ValueError(f"{path} não é um classificador (task={manifest.task})")
        unknown = set(manifest.labels) - set(CLASSIFIER_LABELS)
        if unknown:
            raise ValueError(f"Rótulos desconhecidos no classificador: {sorted(unknown)}")
        self.name = manifest.tag
        self.labels = manifest.labels
        self.thresholds = {label: manifest.thresholds.get(label, 0.5) for label in self.labels}
        self.batch_size = batch_size
        self.bundle.tokenizer.enable_truncation(manifest.max_length, strategy="only_second")

    def predict(self, messages: Sequence[MessageInput]) -> list[dict[str, float]]:
        results: list[dict[str, float]] = [{} for _ in messages]
        pending = [i for i, m in enumerate(messages) if m.text.strip()]
        for begin in range(0, len(pending), self.batch_size):
            indexes = pending[begin : begin + self.batch_size]
            encodings = self.bundle.tokenizer.encode_batch(
                [classifier_pair(messages[i].sender, messages[i].text) for i in indexes]
            )
            probabilities = sigmoid(self.bundle.run(encodings))
            for i, row in zip(indexes, probabilities, strict=True):
                results[i] = {label: float(p) for label, p in zip(self.labels, row, strict=True)}
        return results
