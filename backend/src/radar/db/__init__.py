"""Persistência: modelos SQLAlchemy, sessões e tipos portáveis."""

from radar.db.base import Base, new_uuid, utcnow
from radar.db.session import (
    TenantIsolationError,
    get_engine,
    get_sessionmaker,
    new_session,
    reset_engine,
    scope_session,
    session_scope,
)

__all__ = [
    "Base",
    "TenantIsolationError",
    "get_engine",
    "get_sessionmaker",
    "new_session",
    "new_uuid",
    "reset_engine",
    "scope_session",
    "session_scope",
    "utcnow",
]
