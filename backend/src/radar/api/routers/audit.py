"""Consulta à trilha de auditoria."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from radar.api.deps import DbDep, require
from radar.api.schemas.common import Page, Pagination, pagination
from radar.api.schemas.core import AuditLogOut
from radar.auth.principal import Permission, Principal
from radar.db.models import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["auditoria"])

AuditorDep = Annotated[Principal, Depends(require(Permission.AUDIT_READ))]


@router.get("", response_model=Page[AuditLogOut], summary="Listar registros de auditoria")
def list_audit_logs(
    db: DbDep,
    _principal: AuditorDep,
    page: Annotated[Pagination, Depends(pagination)],
    action: Annotated[str | None, Query(description="Prefixo da ação, ex.: conversation.")] = None,
    actor: Annotated[str | None, Query(description="Trecho do e-mail ou nome do token")] = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    since: Annotated[datetime | None, Query(description="A partir de (ISO 8601)")] = None,
    until: Annotated[datetime | None, Query(description="Até (ISO 8601)")] = None,
) -> Page[AuditLogOut]:
    filters = []
    if action:
        filters.append(AuditLog.action.startswith(action, autoescape=True))
    if actor:
        filters.append(AuditLog.actor_label.icontains(actor, autoescape=True))
    if resource_type:
        filters.append(AuditLog.resource_type == resource_type)
    if resource_id:
        filters.append(AuditLog.resource_id == resource_id)
    if since:
        filters.append(AuditLog.created_at >= since)
    if until:
        filters.append(AuditLog.created_at <= until)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return Page(
        items=[AuditLogOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
