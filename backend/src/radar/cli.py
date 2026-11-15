"""CLI ``radar``: administração da instalação."""

from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import select

from radar import __version__
from radar.config import get_settings
from radar.db.models import Tenant
from radar.db.session import session_scope
from radar.logs import configure_logging
from radar.runtime import bootstrap as run_bootstrap
from radar.runtime import init_storage
from radar.services.accounts import AccountError, create_tenant, create_user
from radar.taxonomy import Role
from radar.textutil import plural

app = typer.Typer(
    name="radar",
    help="Radar de Vendas: administração da instalação.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _setup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.json_logs)


@app.command()
def version() -> None:
    """Mostra a versão instalada."""
    typer.echo(__version__)


@app.command("init-db")
def init_db() -> None:
    """Cria pastas de dados e, no modo leve (SQLite), as tabelas."""
    settings = get_settings()
    init_storage(settings)
    typer.echo(f"Armazenamento pronto em {settings.data_dir.resolve()}")
    if not settings.is_sqlite:
        typer.echo("PostgreSQL detectado: rode `alembic upgrade head` para criar o esquema.")


@app.command("create-tenant")
def create_tenant_cmd(
    name: Annotated[str, typer.Argument(help="Nome da empresa")],
    playbook: Annotated[str, typer.Option(help="Playbook padrão")] = "generico",
) -> None:
    """Cria uma empresa."""
    with session_scope() as db:
        tenant = create_tenant(db, name, default_playbook=playbook)
        typer.echo(f"Empresa criada: {tenant.name} (slug: {tenant.slug}, id: {tenant.id})")


@app.command("create-user")
def create_user_cmd(
    tenant_slug: Annotated[str, typer.Argument(help="Slug da empresa")],
    email: Annotated[str, typer.Argument(help="E-mail de login")],
    name: Annotated[str, typer.Option(help="Nome da pessoa")] = "Administrador",
    role: Annotated[Role, typer.Option(help="Papel")] = Role.ADMIN,
    password: Annotated[
        str,
        typer.Option(
            prompt=True, confirmation_prompt=True, hide_input=True, help="Senha (10+ caracteres)"
        ),
    ] = "",
) -> None:
    """Cria um usuário numa empresa existente."""
    with session_scope() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            typer.secho(f"Empresa '{tenant_slug}' não encontrada.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        try:
            user = create_user(
                db, tenant_id=tenant.id, email=email, name=name, role=role, password=password
            )
        except AccountError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"Usuário criado: {user.email} ({user.role.value}) em {tenant.name}")


@app.command("retention-run")
def retention_run(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Só mostra o que seria apagado")
    ] = False,
) -> None:
    """Aplica a política de retenção (LGPD) de todas as empresas agora."""
    from radar.services.retention import run_retention_all

    settings = get_settings()
    reports = run_retention_all(settings, dry_run=dry_run)
    with session_scope() as db:
        names = {tenant.id: tenant.name for tenant in db.scalars(select(Tenant))}
    if dry_run:
        typer.echo("Simulação: nada foi apagado.")
    for report in reports:
        typer.echo(
            f"{names.get(report.tenant_id, report.tenant_id)}: "
            f"{plural(report.raw_messages_purged, 'mensagem', 'mensagens')} com texto original, "
            f"{plural(report.media_files_deleted, 'áudio', 'áudios')}, "
            f"{plural(report.conversations_deleted, 'conversa', 'conversas')}"
        )


@app.command("seed-demo")
def seed_demo_cmd(
    password: Annotated[
        str,
        typer.Option(
            prompt=True, hide_input=True, help="Senha dos usuários da demonstração (10+ caracteres)"
        ),
    ] = "",
) -> None:
    """Cria a empresa "Demonstração" com as conversas sintéticas de exemplo."""
    from radar.services.demo import DEMO_USERS, seed_demo

    settings = get_settings()
    if settings.environment == "prod":
        typer.secho(
            "A demonstração não pode ser carregada em produção.", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)
    init_storage(settings)
    try:
        result = seed_demo(settings, password=password)
    except AccountError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if not result.created:
        typer.echo("A empresa de demonstração já existe; nada foi alterado.")
        return
    typer.echo(f"Demonstração pronta com {result.conversations} conversas. Entre com:")
    for email, _name, role in DEMO_USERS:
        typer.echo(f"  {email} ({role.value})")


@app.command()
def models() -> None:
    """Mostra os modelos próprios em uso (NER e classificador) e de onde vieram."""
    from radar.ml.loader import load_classifier, load_ner

    settings = get_settings()
    for label, choice, model in (
        ("NER de dados pessoais", settings.ner_model, load_ner(settings)),
        ("Classificador de mensagens", settings.classifier_model, load_classifier(settings)),
    ):
        if model is None:
            status = "desligado" if choice == "off" else "não encontrado (a camada fica de fora)"
            typer.echo(f"{label}: {status} [{choice}]")
        else:
            typer.echo(f"{label}: {model.name} em {model.bundle.path} [{choice}]")
    typer.echo(f"Pasta de modelos: {settings.models_dir}")


@app.command()
def bootstrap() -> None:
    """Prepara o primeiro uso: pastas e admin inicial (se configurado no .env).

    A demonstração (``RADAR_SEED_DEMO``) é carregada pela API na primeira subida, quando a fila
    de jobs já está no ar; para carregá-la na hora, use ``radar seed-demo``.
    """
    settings = get_settings()
    init_storage(settings)
    run_bootstrap(settings)
    typer.echo("Bootstrap concluído.")


@app.command()
def worker(
    burst: Annotated[bool, typer.Option(help="Processa o que houver na fila e encerra")] = False,
) -> None:
    """Sobe um worker que consome a fila de jobs (exige RADAR_QUEUE_MODE=rq)."""
    from radar.worker.runner import run_worker

    if get_settings().queue_mode != "rq":
        typer.secho(
            "O worker só é necessário com RADAR_QUEUE_MODE=rq. Nos modos inline e sync os jobs "
            "rodam dentro da própria API.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=1)
    run_worker(burst=burst)


@app.command()
def scheduler() -> None:
    """Sobe o agendador de tarefas periódicas (retenção, conversas ociosas…)."""
    from radar.worker.runner import run_scheduler

    run_scheduler()


if __name__ == "__main__":
    app()
