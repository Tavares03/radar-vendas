"""``radar-train``: comparar encoders, treinar, avaliar, exportar e publicar os modelos próprios."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from radar_training.dataset import dataset_manifest, default_dataset_dir, load_messages, load_ner

app = typer.Typer(
    help="Treino e avaliação dos modelos próprios do Radar de Vendas.", no_args_is_help=True
)

REPORTS = Path("training/reports")


@app.callback()
def _utf8() -> None:
    # O exportador do PyTorch escreve emoji; o console do Windows (cp1252) quebraria a execução.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


DatasetOption = Annotated[
    Path | None, typer.Option(help="Pasta do dataset (padrão: data/generated/<versão atual>)")
]


def _dataset(path: Path | None) -> Path:
    return path or default_dataset_dir()


@app.command()
def encoders(
    dataset: DatasetOption = None,
    candidate: Annotated[list[str] | None, typer.Option(help="Encoder a comparar (repita)")] = None,
    epochs: Annotated[int, typer.Option(help="Épocas por tarefa")] = 1,
    seed: Annotated[int, typer.Option(help="Semente")] = 20261114,
    out: Annotated[Path, typer.Option(help="Pasta dos relatórios")] = REPORTS,
) -> None:
    """Compara encoders candidatos nas duas tarefas (escolha da base)."""
    from radar_training.encoders import CANDIDATES, compare, write

    folder = _dataset(dataset)
    data = {
        "ner_train": load_ner(folder, "train"),
        "ner_validation": load_ner(folder, "validation"),
        "msg_train": load_messages(folder, "train"),
        "msg_validation": load_messages(folder, "validation"),
    }
    results = compare(candidate or CANDIDATES, data, epochs=epochs, seed=seed, log=typer.echo)
    write(results, out, dataset_version=dataset_manifest(folder)["version"], epochs=epochs)
    typer.echo(f"Relatório em {out / 'encoders.md'}")


ModelsOption = Annotated[Path, typer.Option(help="Pasta dos modelos")]
NamespaceOption = Annotated[
    str, typer.Option(help="Usuário ou organização no Hugging Face (vai para o model card)")
]


def _llm_router(task: str, enabled: bool) -> object | None:
    """Roteador para o baseline zero-shot: nuvem para o classificador, só local para o NER."""
    if not enabled:
        return None
    from radar.llm import build_router

    router = build_router(mode="local") if task == "ner" else build_router()
    if router is None:
        typer.echo("Sem provedor de LLM disponível: o baseline zero-shot fica de fora.", err=True)
    return router


@app.command()
def run(
    config: Annotated[str, typer.Argument(help="Nome em training/configs/ ou caminho do YAML")],
    dataset: DatasetOption = None,
    models: ModelsOption = Path("models"),
    reports: Annotated[Path, typer.Option(help="Pasta dos relatórios")] = REPORTS,
    namespace: NamespaceOption = "SEU_USUARIO",
    skip_train: Annotated[bool, typer.Option(help="Reaproveita os pesos já treinados")] = False,
    llm: Annotated[bool, typer.Option(help="Inclui o baseline LLM zero-shot")] = False,
) -> None:
    """Treina, exporta para ONNX (int8), calibra, avalia e escreve relatório e model card."""
    from radar_training.config import load_config
    from radar_training.pipeline import evaluate, export, train

    settings = load_config(config)
    folder = _dataset(dataset)
    target = models / settings.name
    if not skip_train:
        train(settings, folder, target, typer.echo)
    export(settings, folder, target, typer.echo)
    evaluate(
        target,
        folder,
        reports,
        namespace=namespace,
        llm_router=_llm_router(settings.task, llm),
        log=typer.echo,
    )
    typer.echo(f"Modelo em {target}; relatório em {reports / settings.name}.md")


@app.command("evaluate")
def evaluate_cmd(
    name: Annotated[str, typer.Argument(help="Nome do modelo (pasta em --models)")],
    dataset: DatasetOption = None,
    models: ModelsOption = Path("models"),
    reports: Annotated[Path, typer.Option(help="Pasta dos relatórios")] = REPORTS,
    namespace: NamespaceOption = "SEU_USUARIO",
    llm: Annotated[bool, typer.Option(help="Inclui o baseline LLM zero-shot")] = False,
) -> None:
    """Reavalia um modelo já exportado (sem treinar de novo)."""
    import json

    from radar.ml.bundle import MANIFEST
    from radar_training.pipeline import evaluate

    target = models / name
    task = json.loads((target / MANIFEST).read_text(encoding="utf-8"))["task"]
    evaluate(
        target,
        _dataset(dataset),
        reports,
        namespace=namespace,
        llm_router=_llm_router(task, llm),
        log=typer.echo,
    )
    typer.echo(f"Relatório em {reports / name}.md")


@app.command()
def publish(
    name: Annotated[str, typer.Argument(help="Nome do modelo (pasta em --models)")],
    namespace: Annotated[str, typer.Option(help="Usuário ou organização no Hugging Face")],
    models: ModelsOption = Path("models"),
    yes: Annotated[
        bool, typer.Option("--yes", help="Publica de verdade (sem isso, só mostra o plano)")
    ] = False,
) -> None:
    """Publica o modelo no Hugging Face Hub (precisa de HF_TOKEN com escrita)."""
    import os

    from radar_training.publish import dataset_id, model_plan, publish_folder

    folder = models / name
    repo_id = f"{namespace}/{name}"
    files = model_plan(folder, repo_id, dataset_id=dataset_id(namespace))
    total = sum(p.stat().st_size for p in files) / 1_000_000
    typer.echo(f"{repo_id}: {len(files)} arquivos, {total:.0f} MB")
    for path in files:
        typer.echo(f"  {path.relative_to(folder).as_posix()}")
    if not yes:
        typer.echo("Só o plano. Para publicar: --yes (com HF_TOKEN no ambiente).")
        return
    token = os.environ.get("HF_TOKEN")
    if not token:
        typer.echo("Defina HF_TOKEN (token com escrita do Hugging Face).", err=True)
        raise typer.Exit(code=1)
    typer.echo(publish_folder(folder, repo_id, repo_type="model", files=files, token=token))


if __name__ == "__main__":
    app()
