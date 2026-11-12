"""Engine, sessões e isolamento automático por empresa."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker, with_loader_criteria
from sqlalchemy.pool import StaticPool

from radar.config import get_settings
from radar.db.base import TenantScoped

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None

TENANT_KEY = "tenant_id"


class TenantIsolationError(RuntimeError):
    """Tentativa de gravar um registro de outra empresa na sessão atual."""


def _build_engine(url: str) -> Engine:
    parsed = make_url(url)
    kwargs: dict[str, Any] = {"future": True}
    if parsed.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if parsed.database in (None, "", ":memory:"):
            kwargs["poolclass"] = StaticPool
        else:
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
    engine = create_engine(url, **kwargs)

    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings().database_url)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=True)
    return _sessionmaker


def reset_engine() -> None:
    """Fecha o engine atual; o próximo uso recria a partir da configuração (testes)."""
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None


def new_session(tenant_id: uuid.UUID | None = None) -> Session:
    session = get_sessionmaker()()
    if tenant_id is not None:
        scope_session(session, tenant_id)
    return session


def scope_session(session: Session, tenant_id: uuid.UUID) -> None:
    """Prende a sessão a uma empresa: daqui em diante só enxerga e grava dados dela."""
    session.info[TENANT_KEY] = tenant_id


@contextmanager
def session_scope(tenant_id: uuid.UUID | None = None) -> Iterator[Session]:
    """Sessão transacional: faz commit ao sair e rollback em caso de erro."""
    session = new_session(tenant_id)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state: ORMExecuteState) -> None:
    tenant_id = state.session.info.get(TENANT_KEY)
    if tenant_id is None or state.execution_options.get("skip_tenant_filter", False):
        return
    if state.is_select and not state.is_column_load and not state.is_relationship_load:
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantScoped,
                lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True,
            )
        )


@event.listens_for(Session, "before_flush")
def _guard_tenant_writes(session: Session, _flush_context: Any, _instances: Any) -> None:
    tenant_id = session.info.get(TENANT_KEY)
    if tenant_id is None:
        return
    for obj in [*session.new, *session.dirty]:
        if not isinstance(obj, TenantScoped):
            continue
        # Antes do flush a coluna pode estar vazia, apesar de o tipo dizer que não.
        current: uuid.UUID | None = getattr(obj, "tenant_id", None)
        if current is None:
            obj.tenant_id = tenant_id
        elif current != tenant_id:
            raise TenantIsolationError(
                f"{type(obj).__name__} pertence a outra empresa e não pode ser gravado nesta sessão"
            )
