"""CLI ``radar-synth``: gera, revisa e empacota o dataset sintético."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from radar_synth.banks import SECTORS, load_bank
from radar_synth.challenge import load_challenge
from radar_synth.dataset import SPLITS, build_dataset, dataset_version, write_dataset
from radar_synth.generator import generate_conversation
from radar_synth.model import SynthConversation
from radar_synth.writers import export_zip

app = typer.Typer(
    name="radar-synth",
    help="Gerador de conversas de venda sintéticas e anotadas (PT-BR, formato WhatsApp).",
    no_args_is_help=True,
    add_completion=False,
)


def _load_conversations(path: Path) -> list[SynthConversation]:
    return [
        SynthConversation.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@app.command()
def generate(
    out: Annotated[Path, typer.Option(help="Pasta de saída")] = Path("data/generated"),
    train: Annotated[int, typer.Option(help="Conversas de treino")] = 3000,
    validation: Annotated[int, typer.Option(help="Conversas de validação")] = 500,
    test: Annotated[int, typer.Option(help="Conversas de teste")] = 500,
    seed: Annotated[int, typer.Option(help="Semente (mesma semente = mesmo dataset)")] = 20261113,
    exports: Annotated[int, typer.Option(help="Exports .zip de exemplo por split")] = 20,
    ood: Annotated[
        Path | None, typer.Option(help="JSONL do conjunto fora de distribuição a incluir")
    ] = None,
) -> None:
    """Gera o dataset completo em ``<out>/<versão>/``."""
    conversations = build_dataset(
        sizes={"train": train, "validation": validation, "test": test}, seed=seed
    )
    conversations += list(load_challenge())
    if ood is not None:
        conversations += _load_conversations(ood)
    target = out / dataset_version()
    manifest = write_dataset(conversations, target, exports_per_split=exports, seed=seed)
    typer.echo(f"Dataset {manifest['version']} em {target}")
    for split, count in manifest["conversations"].items():
        typer.echo(f"  {split}: {count} conversas, {manifest['messages'][split]} mensagens")


@app.command()
def sample(
    out: Annotated[Path, typer.Option(help="Arquivo .zip de saída")],
    sector: Annotated[str, typer.Option(help=f"Setor: {', '.join(SECTORS)}")] = "consorcio",
    seed: Annotated[int, typer.Option(help="Semente")] = 1,
    seller: Annotated[str | None, typer.Option(help="bom | medio | problematico")] = None,
    platform: Annotated[str, typer.Option(help="android | ios")] = "android",
    language: Annotated[str, typer.Option(help="pt | en")] = "pt",
) -> None:
    """Gera uma conversa e grava o export .zip (para testar a importação)."""
    conversation = generate_conversation(seed=seed, sector=sector, seller_profile=seller)
    _, data = export_zip(conversation, platform=platform, language=language)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    alerts = ", ".join(a.type for a in conversation.expected_alerts) or "nenhum"
    typer.echo(f"{out} ({len(conversation.messages)} mensagens; alertas esperados: {alerts})")


@app.command()
def samples(
    out: Annotated[Path, typer.Option(help="Pasta de saída")] = Path("data/samples/synthetic"),
    per_sector: Annotated[int, typer.Option(help="Conversas por setor")] = 2,
) -> None:
    """Gera as amostras pequenas versionadas no repositório (demo, testes e Space)."""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    profiles = ("problematico", "bom", "medio")
    for sector in SECTORS:
        for index in range(per_sector):
            conversation = generate_conversation(
                seed=index + 1,
                sector=sector,
                seller_profile=profiles[index % len(profiles)],
                conversation_id=f"amostra-{sector}-{index + 1}",
            )
            _name, data = export_zip(conversation, platform=("android", "ios")[index % 2])
            (out / f"{conversation.id}.zip").write_bytes(data)
            rows.append(json.dumps(conversation.to_dict(), ensure_ascii=False, sort_keys=True))
    (out / "anotacoes.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    typer.echo(f"{len(rows)} conversas de exemplo em {out}")


@app.command()
def demo(
    out: Annotated[Path, typer.Option(help="Pasta de saída")] = Path("data/samples/demo"),
    seed: Annotated[int, typer.Option(help="Semente")] = 7,
) -> None:
    """Gera os exports da demonstração: uma equipe de consórcio ao longo de oito semanas."""
    from radar_synth.demo import write_demo

    count = write_demo(out, seed)
    typer.echo(f"{count} conversas da demonstração em {out}")


@app.command()
def review(
    dataset: Annotated[Path, typer.Option(help="Pasta do dataset gerado")],
    n: Annotated[int, typer.Option(help="Conversas na amostra")] = 40,
    seed: Annotated[int, typer.Option(help="Semente da amostra")] = 0,
    out: Annotated[Path, typer.Option(help="Pasta da revisão")] = Path("data/review"),
) -> None:
    """Separa uma amostra para revisão humana (Markdown + planilha CSV)."""
    from radar_synth.review import select_review_sample, write_review

    conversations = [
        conversation
        for split in SPLITS
        for conversation in _load_conversations(dataset / "conversations" / f"{split}.jsonl")
    ]
    markdown, sheet = write_review(select_review_sample(conversations, n=n, seed=seed), out)
    typer.echo(f"Leia {markdown} e preencha {sheet}")


@app.command()
def expand(
    provider: Annotated[str, typer.Option(help="groq | gemini | openrouter | ollama")] = "groq",
    per_family: Annotated[int, typer.Option(help="Variantes novas por família")] = 3,
    max_families: Annotated[int | None, typer.Option(help="Limite de famílias (teste)")] = None,
    origin: Annotated[
        list[str] | None, typer.Option(help="comum e/ou setores (padrão: todos)")
    ] = None,
) -> None:
    """Pede paráfrases a um LLM gratuito e guarda as válidas em banks/expanded/."""
    from radar_synth.expand import expand_bank, save_expansions
    from radar_synth.llm import LLMError, client_for

    try:
        client = client_for(provider)
    except LLMError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    for name in origin or ["comum", *SECTORS]:
        bank = load_bank(name if name in SECTORS else "generico")
        expansions = expand_bank(
            client, bank, origin=name, per_family=per_family, max_families=max_families
        )
        total = sum(len(v) for families in expansions.values() for v in families.values())
        path = save_expansions(name, expansions)
        typer.echo(f"{name}: {total} variantes novas em {path}")
    typer.echo("Rode `radar-synth generate` de novo: a versão do dataset mudou.")


@app.command()
def ood(
    out: Annotated[Path, typer.Option(help="Arquivo JSONL de saída")] = Path("data/ood/ood.jsonl"),
    provider: Annotated[str, typer.Option(help="Use um LLM diferente do da expansão")] = "gemini",
    n: Annotated[int, typer.Option(help="Conversas")] = 40,
    seed: Annotated[int, typer.Option(help="Semente dos cenários")] = 0,
) -> None:
    """Conjunto fora de distribuição: conversas escritas inteiras por um LLM."""
    from radar_synth.llm import LLMError, client_for
    from radar_synth.ood import generate_ood_conversation

    try:
        client = client_for(provider)
    except LLMError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    rows = []
    for index in range(n):
        sector = SECTORS[index % len(SECTORS)]
        try:
            conversation = generate_ood_conversation(client, seed=seed + index, sector=sector)
        except LLMError as exc:
            typer.secho(f"conversa {index} descartada: {exc}", fg=typer.colors.YELLOW, err=True)
            continue
        rows.append(json.dumps(conversation.to_dict(), ensure_ascii=False, sort_keys=True))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    typer.echo(f"{len(rows)} conversas em {out}. Revise antes de usar nos evals.")


@app.command("export-hf")
def export_hf(
    dataset: Annotated[Path, typer.Option(help="Pasta do dataset gerado")],
    out: Annotated[Path, typer.Option(help="Pasta do pacote")] = Path(
        "data/hf/radar-vendas-conversas-sinteticas"
    ),
) -> None:
    """Monta a pasta para o Hugging Face Hub (arquivos + dataset card)."""
    from radar_synth.hf import build_hf_folder

    folder = build_hf_folder(dataset, out)
    typer.echo(f"Pacote pronto em {folder}. Publique com: python scripts/publish_hf.py dataset")


if __name__ == "__main__":
    app()
