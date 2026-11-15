"""Publica o dataset e os modelos do Radar no Hugging Face Hub.

Sem ``--yes`` só mostra o plano. Precisa de ``HF_TOKEN`` (token com escrita, gratuito).

    uv run python scripts/publish_hf.py dataset --namespace SEU_USUARIO
    uv run python scripts/publish_hf.py model pii-ner-ptbr --namespace SEU_USUARIO
    uv run python scripts/publish_hf.py tudo --namespace SEU_USUARIO --yes

O pacote do dataset sai de ``uv run radar-synth export-hf --dataset data/generated/<versão>``;
os modelos, de ``uv run radar-train run <modelo>`` (extra ``train``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "data" / "hf" / "radar-vendas-conversas-sinteticas"
MODELS = ("pii-ner-ptbr", "sales-intent-ptbr")

app = typer.Typer(help=__doc__, no_args_is_help=True)

Namespace = Annotated[str, typer.Option(help="Usuário ou organização no Hugging Face")]
Yes = Annotated[bool, typer.Option("--yes", help="Publica de verdade (sem isso, só o plano)")]


def _token(yes: bool) -> str | None:
    token = os.environ.get("HF_TOKEN")
    if yes and not token:
        typer.echo("Defina HF_TOKEN (token com escrita do Hugging Face).", err=True)
        raise typer.Exit(code=1)
    return token


def _show(repo_id: str, folder: Path, files: list[Path]) -> None:
    total = sum(p.stat().st_size for p in files) / 1_000_000
    typer.echo(f"{repo_id}: {len(files)} arquivos, {total:.0f} MB")
    for path in files:
        typer.echo(f"  {path.relative_to(folder).as_posix()}")


@app.command()
def dataset(namespace: Namespace, folder: Path = DATASET_DIR, yes: Yes = False) -> None:
    """Publica o dataset sintético (CC BY 4.0)."""
    from radar_training.publish import dataset_id, publish_folder

    if not (folder / "README.md").is_file():
        typer.echo(
            f"{folder} não tem o pacote. Rode: uv run radar-synth export-hf --dataset <pasta>",
            err=True,
        )
        raise typer.Exit(code=1)
    repo_id = dataset_id(namespace)
    files = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    _show(repo_id, folder, files)
    if yes:
        typer.echo(
            publish_folder(folder, repo_id, repo_type="dataset", files=files, token=_token(yes))
        )


@app.command()
def model(
    name: Annotated[str, typer.Argument(help="pii-ner-ptbr ou sales-intent-ptbr")],
    namespace: Namespace,
    models: Path = ROOT / "models",
    yes: Yes = False,
) -> None:
    """Publica um modelo (pesos do Transformers, ONNX e model card)."""
    from radar_training.publish import dataset_id, model_plan, publish_folder

    folder = models / name
    repo_id = f"{namespace}/{name}"
    files = model_plan(folder, repo_id, dataset_id=dataset_id(namespace))
    _show(repo_id, folder, files)
    if yes:
        typer.echo(
            publish_folder(folder, repo_id, repo_type="model", files=files, token=_token(yes))
        )


@app.command()
def tudo(namespace: Namespace, yes: Yes = False) -> None:
    """Dataset e os dois modelos."""
    dataset(namespace, DATASET_DIR, yes)
    for name in MODELS:
        model(name, namespace, ROOT / "models", yes)
    if not yes:
        typer.echo("Só o plano. Para publicar: --yes (com HF_TOKEN no ambiente).")


if __name__ == "__main__":
    sys.exit(app())
