"""Tokens de API para integrações (CRM, N8N, scripts)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from radar.api.deps import DbDep, request_meta, require
from radar.api.errors import NotFound
from radar.api.schemas.core import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from radar.auth.principal import Permission, Principal
from radar.auth.tokens import generate_api_token
from radar.db.models import ApiToken
from radar.services.audit import AuditAction, record_audit

router = APIRouter(prefix="/api-tokens", tags=["integrações"])

AdminDep = Annotated[Principal, Depends(require(Permission.SETTINGS_MANAGE))]


@router.get("", response_model=list[ApiTokenOut], summary="Listar tokens de API")
def list_tokens(db: DbDep, _principal: AdminDep) -> list[ApiTokenOut]:
    rows = db.scalars(select(ApiToken).order_by(ApiToken.created_at.desc())).all()
    return [ApiTokenOut.model_validate(row) for row in rows]


@router.post("", response_model=ApiTokenCreated, status_code=201, summary="Criar token de API")
def create(
    body: ApiTokenCreate, request: Request, db: DbDep, principal: AdminDep
) -> ApiTokenCreated:
    """O valor do token aparece **uma única vez**, nesta resposta."""
    generated = generate_api_token()
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    )
    token = ApiToken(
        tenant_id=principal.tenant_id,
        name=body.name.strip(),
        prefix=generated.prefix,
        token_hash=generated.token_hash,
        scopes=sorted({scope.value for scope in body.scopes}),
        created_by=principal.user_id,
        expires_at=expires_at,
    )
    db.add(token)
    db.flush()
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.TOKEN_CREATED,
        principal=principal,
        resource_type="api_token",
        resource_id=token.id,
        details={"name": token.name, "scopes": token.scopes},
        **request_meta(request),
    )
    db.commit()
    out = ApiTokenOut.model_validate(token)
    return ApiTokenCreated(**out.model_dump(), token=generated.plain)


@router.delete("/{token_id}", status_code=204, summary="Revogar token de API")
def revoke(token_id: uuid.UUID, request: Request, db: DbDep, principal: AdminDep) -> Response:
    token = db.get(ApiToken, token_id)
    if token is None:
        raise NotFound("Token não encontrado.")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.TOKEN_REVOKED,
        principal=principal,
        resource_type="api_token",
        resource_id=token.id,
        details={"name": token.name},
        **request_meta(request),
    )
    db.commit()
    return Response(status_code=204)
