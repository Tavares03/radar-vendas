"""Fila de alertas: listar, ver e revisar (status, responsável, nota)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import ColumnElement, case, select

from radar.api.deps import DbDep, request_meta, require
from radar.api.errors import NotFound
from radar.api.paging import paginate
from radar.api.schemas.analysis import AlertOut, AlertUpdate
from radar.api.schemas.common import Page, Pagination, pagination
from radar.auth.principal import Permission, Principal
from radar.db.models import Alert, User
from radar.services.analysis import refresh_alert_summary
from radar.services.audit import AuditAction, record_audit
from radar.taxonomy import AlertStatus, label_pt

router = APIRouter(prefix="/alerts", tags=["alertas"])

ReaderDep = Annotated[Principal, Depends(require(Permission.ALERTS_READ))]
ReviewerDep = Annotated[Principal, Depends(require(Permission.ALERTS_REVIEW))]

_SEVERITY_ORDER = case({"critico": 0, "atencao": 1, "info": 2}, value=Alert.severity, else_=3)


def alert_out(alert: Alert) -> AlertOut:
    out = AlertOut.model_validate(alert)
    out.label = label_pt(alert.type)
    out.customer_label = alert.conversation.customer_label
    out.seller_name = alert.conversation.seller.display_name if alert.conversation.seller else None
    return out


def _visible(db: DbDep, principal: Principal, alert_id: uuid.UUID) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None or (
        principal.is_seller_restricted and alert.seller_id != principal.only_seller_id
    ):
        raise NotFound("Alerta não encontrado.")
    return alert


@router.get("", response_model=Page[AlertOut], summary="Listar alertas")
def list_alerts(
    db: DbDep,
    principal: ReaderDep,
    page: Annotated[Pagination, Depends(pagination)],
    status: AlertStatus | None = None,
    severity: str | None = None,
    type: str | None = None,
    category: str | None = None,
    seller_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    open_only: bool = False,
) -> Page[AlertOut]:
    """Mais graves primeiro; vendedores veem só os alertas das próprias conversas."""
    filters: list[ColumnElement[bool]] = []
    if principal.is_seller_restricted:
        if principal.only_seller_id is None:
            return Page[AlertOut](items=[], total=0, limit=page.limit, offset=page.offset)
        filters.append(Alert.seller_id == principal.only_seller_id)
    elif seller_id is not None:
        filters.append(Alert.seller_id == seller_id)
    if status is not None:
        filters.append(Alert.status == status)
    if open_only:
        filters.append(
            Alert.status.in_([AlertStatus.ABERTO, AlertStatus.EM_REVISAO, AlertStatus.CONFIRMADO])
        )
    if severity is not None:
        filters.append(Alert.severity == severity)
    if type is not None:
        filters.append(Alert.type == type)
    if category is not None:
        filters.append(Alert.category == category)
    if conversation_id is not None:
        filters.append(Alert.conversation_id == conversation_id)
    rows, total = paginate(
        db, Alert, filters=filters, order_by=[_SEVERITY_ORDER, Alert.created_at.desc()], page=page
    )
    return Page[AlertOut](
        items=[alert_out(row) for row in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{alert_id}", response_model=AlertOut, summary="Ver um alerta")
def get_alert(alert_id: uuid.UUID, db: DbDep, principal: ReaderDep) -> AlertOut:
    return alert_out(_visible(db, principal, alert_id))


@router.patch("/{alert_id}", response_model=AlertOut, summary="Revisar um alerta")
def review_alert(
    alert_id: uuid.UUID, body: AlertUpdate, request: Request, db: DbDep, principal: ReviewerDep
) -> AlertOut:
    """Muda o status (``falso_positivo`` vira dado para melhorar o modelo, com o consentimento da
    empresa), atribui um responsável e registra uma nota. Fica na auditoria."""
    alert = _visible(db, principal, alert_id)
    changes: dict[str, str] = {}
    if body.assigned_to_user_id is not None:
        user = db.scalar(select(User).where(User.id == body.assigned_to_user_id))
        if user is None:
            raise NotFound("Usuário não encontrado.")
        alert.assigned_to_user_id = user.id
        changes["responsavel"] = str(user.id)
    elif body.unassign:
        alert.assigned_to_user_id = None
        changes["responsavel"] = ""
    if body.status is not None and body.status is not alert.status:
        changes["status"] = body.status.value
        alert.status = body.status
    if body.note is not None:
        alert.review_note = body.note.strip()
        changes["nota"] = "atualizada"
    if changes:
        alert.reviewed_by_user_id = principal.user_id
        alert.reviewed_at = datetime.now(UTC)
        refresh_alert_summary(db, alert.conversation)
        record_audit(
            db,
            tenant_id=principal.tenant_id,
            action=AuditAction.ALERT_REVIEWED,
            principal=principal,
            resource_type="alert",
            resource_id=alert.id,
            details={"tipo": alert.type, **changes},
            **request_meta(request),
        )
        db.commit()
        db.refresh(alert)
    return alert_out(alert)
