"""Ambiente do Alembic.

As migrations são autocontidas: tipos próprios do projeto (datas em UTC, enums como texto, texto
cifrado) são renderizados como os tipos SQLAlchemy equivalentes, para que uma migration antiga
continue rodando mesmo que o código da aplicação mude.
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from pgvector.sqlalchemy import Vector
from sqlalchemy import engine_from_config, pool, text

from radar.config import get_settings
from radar.db import models  # noqa: F401  (registra as tabelas)
from radar.db.base import Base
from radar.db.types import EncryptedText, StrEnumType, UtcDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    if type_ != "type":
        return False
    if isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    if isinstance(obj, StrEnumType):
        return f"sa.String(length={obj.impl.length})"
    if isinstance(obj, EncryptedText):
        return "sa.Text()"
    if isinstance(obj, Vector):
        autogen_context.imports.add("import pgvector.sqlalchemy")
        return f"pgvector.sqlalchemy.Vector({obj.dim})"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Um único processo de migration por vez, mesmo com várias réplicas subindo juntas.
            connection.execute(text("SELECT pg_advisory_lock(727464)"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
