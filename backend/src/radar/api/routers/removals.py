"""Pedidos de remoção de conversa: o vendedor pede, só a gestão aprova ou recusa."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.api.deps import DbDep, SettingsDep, request_meta, require
from radar.api.errors import Conflict, NotFound
from radar.api.schemas.conversations import (
    RemovalDecisionIn,
    RemovalRequestIn,
    RemovalRequestOut,
    SellerBrief,
)
from radar.auth.principal import Permission, Principal
from radar.db.models import RemovalRequest, Seller, User
from radar.services.audit import AuditAction, record_audit
from radar.services.conversations import get_visible_conversation
from radar.services.removals import RemovalError, decide, request_removal
from radar.taxonomy import RemovalStatus

router = APIRouter(tags=["conversas"])

WriterDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_WRITE))]
ReaderDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_READ))]
DeciderDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_DELETE))]


def removal_views(db: Session, requests: list[RemovalRequest]) -> list[RemovalRequestOut]:
    user_ids = {
        user_id
        for request in requests
        for user_id in (request.requested_by_user_id, request.decided_by_user_id)
        if user_id is not None
    }
    seller_ids = {request.seller_id for request in requests if request.seller_id is not None}
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    sellers = {s.id: s for s in db.scalars(select(Seller).where(Seller.id.in_(seller_ids)))}
    views = []
    for request in requests:
        seller = sellers.get(request.seller_id) if request.seller_id else None
        views.append(
            RemovalRequestOut(
                id=request.id,
                conversation_id=request.conversation_id,
                conversation_label=request.conversation_label,
                seller=SellerBrief(id=seller.id, display_name=seller.display_name)
                if seller
                else None,
                requested_by=names.get(request.requested_by_user_id, "")
                if request.requested_by_user_id
                else "",
                reason=request.reason,
                status=request.status,
                decided_by=names.get(request.decided_by_user_id, "")
                if request.decided_by_user_id
                else "",
                decided_at=request.decided_at,
                decision_note=request.decision_note,
                created_at=request.created_at,
            )
        )
    return views


@router.post(
    "/conversations/{conversation_id}/removal-request",
    response_model=RemovalRequestOut,
    status_code=201,
    summary="Pedir a remoção de uma conversa",
)
def create_request(
    conversation_id: uuid.UUID,
    body: RemovalRequestIn,
    request: Request,
    db: DbDep,
    principal: WriterDep,
) -> RemovalRequestOut:
    """O vendedor pede para tirar uma conversa do Radar (ex.: é pessoal). A conversa continua
    visível e analisada até a gestão decidir."""
    conversation = get_visible_conversation(db, principal, conversation_id)
    if conversation is None:
        raise NotFound("Conversa não encontrada.")
    try:
        removal = request_removal(
            db, principal=principal, conversation=conversation, reason=body.reason
        )
    except RemovalError as exc:
        raise Conflict(str(exc)) from exc
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.REMOVAL_REQUESTED,
        principal=principal,
        resource_type="conversation",
        resource_id=conversation.id,
        details={"pedido": str(removal.id), "motivo": removal.reason[:300]},
        **request_meta(request),
    )
    db.commit()
    return removal_views(db, [removal])[0]


@router.get(
    "/removal-requests",
    response_model=list[RemovalRequestOut],
    summary="Listar pedidos de remoção",
)
def list_requests(
    db: DbDep,
    principal: ReaderDep,
    status: Annotated[RemovalStatus | None, Query()] = RemovalStatus.PENDENTE,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RemovalRequestOut]:
    """A gestão vê todos; quem não pode decidir vê só os pedidos que fez."""
    query = select(RemovalRequest).order_by(RemovalRequest.created_at.desc()).limit(limit)
    if status is not None:
        query = query.where(RemovalRequest.status == status)
    if not principal.can(Permission.CONVERSATIONS_DELETE):
        query = query.where(RemovalRequest.requested_by_user_id == principal.user_id)
    return removal_views(db, list(db.scalars(query)))


def _decide(
    request_id: uuid.UUID,
    body: RemovalDecisionIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: Principal,
    *,
    approve: bool,
) -> RemovalRequestOut:
    removal = db.get(RemovalRequest, request_id)
    if removal is None:
        raise NotFound("Pedido não encontrado.")
    conversation_id = removal.conversation_id
    try:
        ignored = decide(
            db,
            principal=principal,
            request=removal,
            approve=approve,
            note=body.note,
            stop_capturing=body.stop_capturing,
            settings=settings,
        )
    except RemovalError as exc:
        raise Conflict(str(exc)) from exc
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.REMOVAL_APPROVED if approve else AuditAction.REMOVAL_REJECTED,
        principal=principal,
        resource_type="conversation",
        resource_id=conversation_id or "",
        details={
            "pedido": str(removal.id),
            "conversa": removal.conversation_label,
            "nota": removal.decision_note[:300],
            "contato_ignorado": ignored,
        },
        **request_meta(request),
    )
    if approve:
        record_audit(
            db,
            tenant_id=principal.tenant_id,
            action=AuditAction.CONVERSATION_DELETED,
            principal=principal,
            resource_type="conversation",
            resource_id=conversation_id or "",
            details={"pedido_de_remocao": str(removal.id)},
            **request_meta(request),
        )
    db.commit()
    return removal_views(db, [removal])[0]


@router.post(
    "/removal-requests/{request_id}/approve",
    response_model=RemovalRequestOut,
    summary="Aprovar um pedido de remoção (apaga a conversa)",
)
def approve(
    request_id: uuid.UUID,
    body: RemovalDecisionIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: DeciderDep,
) -> RemovalRequestOut:
    """Apaga a conversa, as mensagens, os áudios e as análises. Para conversas do WhatsApp
    conectado, com `stop_capturing` o contato também deixa de ser capturado."""
    return _decide(request_id, body, request, db, settings, principal, approve=True)


@router.post(
    "/removal-requests/{request_id}/reject",
    response_model=RemovalRequestOut,
    summary="Recusar um pedido de remoção (a conversa fica)",
)
def reject(
    request_id: uuid.UUID,
    body: RemovalDecisionIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: DeciderDep,
) -> RemovalRequestOut:
    return _decide(request_id, body, request, db, settings, principal, approve=False)
