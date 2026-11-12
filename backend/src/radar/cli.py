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


@app.command()
def bootstrap() -> None:
    """Prepara o primeiro uso: pastas, admin inicial (se configurado no .env) e dados da demo."""
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
