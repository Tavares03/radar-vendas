"""Configuração versionada de um treino (``training/configs/<modelo>.yaml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


class TrainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    task: Literal["ner", "classifier"]
    #: Versão publicada do modelo (vai para o manifesto e o model card).
    version: str
    base_model: str
    #: Licença da base (vai para o model card; precisa ser compatível com Apache-2.0).
    base_license: str = "MIT"
    seed: int = 20261114
    max_length: int = Field(default=128, ge=16, le=512)
    #: Sobreposição das janelas de texto longo, no runtime do NER.
    stride: int = Field(default=32, ge=0)
    batch_size: int = Field(default=32, ge=1)
    epochs: int = Field(default=4, ge=1)
    learning_rate: float = Field(default=5e-5, gt=0)
    warmup_ratio: float = Field(default=0.1, ge=0, lt=1)
    weight_decay: float = Field(default=0.01, ge=0)
    #: Épocas sem melhora na validação antes de parar.
    patience: int = Field(default=2, ge=1)
    #: Classificador: precisão mínima de cada rótulo na validação para ele valer em produção.
    #: O rótulo que não alcança isso em limiar nenhum fica desligado no manifesto.
    min_precision: float = Field(default=0.7, ge=0, le=1)


def load_config(name_or_path: str) -> TrainConfig:
    path = Path(name_or_path)
    if not path.suffix:
        path = CONFIGS_DIR / f"{name_or_path}.yaml"
    return TrainConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
