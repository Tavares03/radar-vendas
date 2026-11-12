"""Preparação do ambiente na subida da API, do worker e da CLI."""

from __future__ import annotations

from radar.config import Settings
from radar.db import models  # noqa: F401  (registra as tabelas)
from radar.db.base import Base
from radar.db.session import get_engine, session_scope
from radar.logs import get_logger
from radar.services.accounts import bootstrap_from_settings

log = get_logger(__name__)


def init_storage(settings: Settings) -> None:
    """Cria as pastas de dados e, no modo leve (SQLite), as tabelas.

    Com PostgreSQL o esquema é responsabilidade do Alembic (``alembic upgrade head``).
    """
    for folder in (settings.data_dir, settings.uploads_dir, settings.media_dir, settings.cache_dir):
        folder.mkdir(parents=True, exist_ok=True)
    if settings.is_sqlite:
        Base.metadata.create_all(get_engine())


def bootstrap(settings: Settings) -> None:
    """Cria a empresa e o administrador iniciais, se configurados e o banco estiver vazio."""
    with session_scope() as db:
        bootstrap_from_settings(db, settings)


def prepare_runtime(settings: Settings) -> None:
    init_storage(settings)
    try:
        bootstrap(settings)
    except Exception as exc:
        # Banco ainda sem migrations: a API sobe e /api/ready denuncia o problema.
        log.warning("bootstrap_ignorado", error=str(exc))
