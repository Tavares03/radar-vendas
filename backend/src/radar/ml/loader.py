"""Onde achar os modelos próprios e como carregá-los uma vez por processo.

``RADAR_NER_MODEL`` e ``RADAR_CLASSIFIER_MODEL`` aceitam:

- ``off``: camada desligada;
- ``auto`` (padrão): ``<models_dir>/<nome>`` se existir; senão o id do Hugging Face configurado
  (``RADAR_NER_HUB_ID`` / ``RADAR_CLASSIFIER_HUB_ID``); senão a camada fica de fora;
- um caminho de pasta, ou um id do Hub (``usuario/modelo``).

Falhar ao carregar nunca derruba a análise: o erro vai para o log e a camada fica de fora (a
máscara por regex e as regras continuam).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, cast

from radar.config import Settings, get_settings
from radar.logs import get_logger
from radar.ml.bundle import MANIFEST, ModelManifest

if TYPE_CHECKING:
    from radar.ml.classifier import OnnxMessageClassifier
    from radar.ml.ner import OnnxPiiNer

log = get_logger(__name__)

NER_NAME = "pii-ner-ptbr"
CLASSIFIER_NAME = "sales-intent-ptbr"

#: Arquivos que o runtime precisa (o resto do repositório no Hub é para quem for ajustar o modelo).
RUNTIME_FILES = (MANIFEST, "tokenizer.json", "onnx/model_quantized.onnx", "README.md")

_lock = threading.Lock()
_cache: dict[tuple[str, str, str, str], object] = {}


def download_from_hub(repo_id: str, settings: Settings) -> Path:
    from huggingface_hub import snapshot_download

    target = settings.cache_dir / "models" / repo_id.replace("/", "--")
    path = Path(snapshot_download(repo_id, allow_patterns=list(RUNTIME_FILES), local_dir=target))
    # Modelo cuja quantização foi reprovada no treino aponta para outro arquivo (o fp32).
    manifest = path / MANIFEST
    if manifest.is_file():
        onnx_file = ModelManifest.model_validate_json(manifest.read_text(encoding="utf-8")).onnx
        if not (path / onnx_file).is_file():
            snapshot_download(repo_id, allow_patterns=[onnx_file], local_dir=target)
    return path


def resolve_model_dir(choice: str, name: str, hub_id: str, settings: Settings) -> Path | None:
    """A pasta do modelo, baixando do Hub se for o caso; ``None`` se a camada fica de fora."""
    choice = choice.strip()
    if choice == "off":
        return None
    if choice in ("", "auto"):
        local = settings.models_dir / name
        if (local / MANIFEST).is_file():
            return local
        if not hub_id:
            return None
        choice = hub_id
    path = Path(choice)
    if (path / MANIFEST).is_file():
        return path
    if choice.count("/") == 1 and not path.exists():
        return download_from_hub(choice, settings)
    raise FileNotFoundError(f"{choice}: pasta sem {MANIFEST}")


def _load(kind: str, choice: str, name: str, hub_id: str, settings: Settings) -> object | None:
    key = (kind, choice.strip() or "auto", str(settings.models_dir), hub_id)
    with _lock:
        if key in _cache:
            return _cache[key]
        model: object | None = None
        try:
            path = resolve_model_dir(choice, name, hub_id, settings)
            if path is not None:
                if kind == "ner":
                    from radar.ml.ner import OnnxPiiNer

                    model = OnnxPiiNer(path, threads=settings.ml_threads)
                else:
                    from radar.ml.classifier import OnnxMessageClassifier

                    model = OnnxMessageClassifier(path, threads=settings.ml_threads)
                log.info(
                    "modelo_carregado",
                    tipo=kind,
                    modelo=getattr(model, "name", ""),
                    pasta=str(path),
                )
        except Exception:
            log.exception("modelo_indisponivel", tipo=kind, escolha=choice)
            model = None
        _cache[key] = model
        return model


def load_ner(settings: Settings | None = None) -> OnnxPiiNer | None:
    settings = settings or get_settings()
    model = _load("ner", settings.ner_model, NER_NAME, settings.ner_hub_id, settings)
    return cast("OnnxPiiNer | None", model)


def load_classifier(settings: Settings | None = None) -> OnnxMessageClassifier | None:
    settings = settings or get_settings()
    model = _load(
        "classifier",
        settings.classifier_model,
        CLASSIFIER_NAME,
        settings.classifier_hub_id,
        settings,
    )
    return cast("OnnxMessageClassifier | None", model)


def clear_cache() -> None:
    """Esquece os modelos carregados (testes, ou depois de trocar a pasta de modelos)."""
    with _lock:
        _cache.clear()
