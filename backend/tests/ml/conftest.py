"""Fixtures com os modelos ONNX minúsculos de ``radar.ml.testing``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from radar.ml.testing import tiny_classifier_model, tiny_ner_model


@pytest.fixture
def make_ner_model(tmp_path: Path) -> Callable[..., Path]:
    def _make(folder: Path | None = None, **overrides: object) -> Path:
        return tiny_ner_model(folder or tmp_path / "ner", **overrides)

    return _make


@pytest.fixture
def make_classifier_model(tmp_path: Path) -> Callable[..., Path]:
    def _make(folder: Path | None = None, **overrides: object) -> Path:
        return tiny_classifier_model(folder or tmp_path / "classificador", **overrides)

    return _make
