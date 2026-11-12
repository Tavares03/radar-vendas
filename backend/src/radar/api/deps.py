"""Dependências do FastAPI: sessão de banco, identidade e permissões."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, TypedDict

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.api.errors import Forbidden, Unauthorized
from radar.api.rate_limit import client_ip, enforce
from radar.auth.jwt import InvalidSessionToken, decode_session_token
from radar.auth.principal import (
    ROLE_PERMISSIONS,
    Permission,
    Principal,
    permissions_for_scopes,
)
from radar.auth.tokens import extract_prefix, looks_like_api_token, verify_api_token
from radar.config import Settings, get_settings
from radar.db.models import ApiToken, Tenant, User
from radar.db.session import new_session, scope_session
from radar.logs import bind_context

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LAST_USED_GRANULARITY = timedelta(minutes=1)


def get_db() -> Iterator[Session]:
    """Sessão por requisição. Quem grava faz ``db.commit()``; erro sempre dá rollback."""
    session = new_session()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _credentials(request: Request, settings: Settings) -> tuple[str, bool]:
    """Devolve ``(token, veio_de_cookie)`` ou levanta 401."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token, False
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return api_key, False
    cookie = request.cookies.get(settings.cookie_name, "").strip()
    if cookie:
        return cookie, True
    raise Unauthorized("Autenticação necessária.", headers={"WWW-Authenticate": "Bearer"})


def _principal_from_api_token(db: Session, plain: str) -> Principal:
    prefix = extract_prefix(plain)
    invalid = Unauthorized("Token de API inválido.")
    if prefix is None:
        raise invalid
    token = db.scalar(select(ApiToken).where(ApiToken.prefix == prefix))
    if token is None or not verify_api_token(plain, token.token_hash):
        raise invalid
    now = datetime.now(UTC)
    if token.revoked_at is not None:
        raise Unauthorized("Token de API revogado.")
    if token.expires_at is not None and token.expires_at <= now:
        raise Unauthorized("Token de API expirado.")
    tenant = db.get(Tenant, token.tenant_id)
    if tenant is None or not tenant.is_active:
        raise invalid
    if token.last_used_at is None or now - token.last_used_at > _LAST_USED_GRANULARITY:
        token.last_used_at = now
        db.commit()
    return Principal(
        tenant_id=token.tenant_id,
        permissions=permissions_for_scopes(token.scopes),
        label=f"token:{token.name}",
        token_id=token.id,
    )


def _principal_from_session(db: Session, raw: str) -> Principal:
    invalid = Unauthorized("Sessão inválida ou expirada. Entre novamente.")
    try:
        claims = decode_session_token(raw)
    except InvalidSessionToken:
        raise invalid from None
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active or user.tenant_id != claims.tenant_id:
        raise invalid
    if claims.session_version != user.session_version:
        raise invalid
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise invalid
    return Principal(
        tenant_id=user.tenant_id,
        permissions=ROLE_PERMISSIONS[user.role],
        label=user.email,
        role=user.role,
        user_id=user.id,
        seller_id=user.seller_id,
    )


def get_principal(request: Request, db: DbDep, settings: SettingsDep) -> Principal:
    token, from_cookie = _credentials(request, settings)

    # Defesa extra contra CSRF: o cookie é SameSite=Lax, e além disso recusamos escrita vinda
    # de outro site quando o navegador informa a origem da requisição.
    if (
        from_cookie
        and request.method not in _SAFE_METHODS
        and request.headers.get("sec-fetch-site", "").lower() == "cross-site"
    ):
        raise Forbidden("Requisição de outro site recusada.", code="cross_site_request")

    if looks_like_api_token(token):
        principal = _principal_from_api_token(db, token)
    else:
        principal = _principal_from_session(db, token)

    enforce(
        f"api:{principal.user_id or principal.token_id}",
        settings.rate_limit_per_minute,
    )
    scope_session(db, principal.tenant_id)
    bind_context(
        tenant_id=str(principal.tenant_id),
        actor=str(principal.user_id or principal.token_id),
    )
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require(*permissions: Permission) -> Callable[[Principal], Principal]:
    """Dependência que exige todas as permissões informadas."""

    def _checker(principal: PrincipalDep) -> Principal:
        missing = [p.value for p in permissions if not principal.can(p)]
        if missing:
            raise Forbidden(
                "Você não tem permissão para esta ação.",
                details={"permissoes_necessarias": missing},
            )
        return principal

    return _checker


class RequestMeta(TypedDict):
    ip: str
    user_agent: str


def request_meta(request: Request) -> RequestMeta:
    """IP e agente do cliente, no formato aceito por ``record_audit``."""
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent", "")}
