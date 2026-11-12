"""Tokens de sessão (JWT HS256, curta duração)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from radar.config import get_settings

_ALGORITHM = "HS256"
_ISSUER = "radar-vendas"


class InvalidSessionToken(Exception):
    """Token ausente, malformado, adulterado ou expirado."""


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    #: Versão de sessão do usuário quando o token foi emitido (ver ``User.session_version``).
    session_version: int
    expires_at: datetime


def create_session_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    session_version: int = 0,
    ttl: timedelta | None = None,
) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + (ttl or timedelta(minutes=settings.jwt_ttl_minutes))
    payload = {
        "iss": _ISSUER,
        "sub": str(user_id),
        "tid": str(tenant_id),
        "ver": session_version,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=_ALGORITHM)
    return token, expires_at


def decode_session_token(token: str) -> SessionClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
            options={"require": ["exp", "sub", "tid", "iss", "ver"]},
        )
        return SessionClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            session_version=int(payload["ver"]),
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidSessionToken(str(exc)) from exc
