"""Publicação no Hugging Face Hub (modelos e dataset). Sem ``--yes``, só mostra o plano.

O token vem de ``HF_TOKEN`` (gratuito: https://huggingface.co/settings/tokens, com escrita).
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from radar_training.pipeline import DATASET_NAME
from radar_training.report import render_card

MODEL_FILES = (
    "README.md",
    "radar_model.json",
    "training.json",
    "metrics.json",
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "onnx/model.onnx",
    "onnx/model_quantized.onnx",
)


def model_plan(folder: Path, repo_id: str, *, dataset_id: str) -> list[Path]:
    """Reescreve o model card com o id final e lista os arquivos que vão para o Hub."""
    report = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    (folder / "README.md").write_text(
        render_card(report, repo_id=repo_id, dataset_id=dataset_id), encoding="utf-8", newline="\n"
    )
    files = [
        path
        for path in sorted(folder.rglob("*"))
        if path.is_file()
        and any(fnmatch.fnmatch(path.relative_to(folder).as_posix(), p) for p in MODEL_FILES)
    ]
    missing = {"README.md", "radar_model.json", "onnx/model_quantized.onnx", "tokenizer.json"} - {
        p.relative_to(folder).as_posix() for p in files
    }
    if missing:
        raise FileNotFoundError(f"{folder}: faltam {sorted(missing)}. Rode radar-train run antes.")
    return files


def publish_folder(
    folder: Path, repo_id: str, *, repo_type: str, files: list[Path], token: str | None
) -> str:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type=repo_type, exist_ok=True)
    commit = api.upload_folder(
        folder_path=str(folder),
        repo_id=repo_id,
        repo_type=repo_type,
        allow_patterns=[p.relative_to(folder).as_posix() for p in files],
        commit_message=f"Publica {folder.name}",
    )
    return str(commit)


def dataset_id(namespace: str) -> str:
    return f"{namespace}/{DATASET_NAME}"
