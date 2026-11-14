"""Conversas: envio por API, listagem, leitura, correção e exclusão."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import ColumnElement, select

from radar.api.deps import DbDep, SettingsDep, request_meta, require
from radar.api.errors import BadRequest, Forbidden, NotFound
from radar.api.paging import paginate
from radar.api.routers.alerts import alert_out
from radar.api.schemas.analysis import AnalysisOut, CriterionOut
from radar.api.schemas.common import Message as MessageResponse
from radar.api.schemas.common import Page, Pagination, pagination
from radar.api.schemas.conversations import (
    ConversationDetail,
    ConversationIn,
    ConversationIngested,
    ConversationOut,
    ConversationUpdate,
)
from radar.auth.principal import Permission, Principal
from radar.db.models import Alert, Conversation, Message, Seller, Tenant
from radar.ingest import ParticipantInfo
from radar.services.analysis import current_analysis
from radar.services.audit import AuditAction, record_audit
from radar.services.conversations import (
    can_reveal,
    delete_conversation,
    get_visible_conversation,
    message_views,
    participant_views,
    set_seller_participant,
)
from radar.services.ingestion import (
    IncomingMessage,
    data_path,
    ingest_conversation,
    tenant_timezone,
    to_utc,
)
from radar.taxonomy import ConversationStatus, ImportSource, MessageKind, SenderRole
from radar.worker.jobs import enqueue_conversation

router = APIRouter(prefix="/conversations", tags=["conversas"])

WriterDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_WRITE))]
ReaderDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_READ))]
DeleterDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_DELETE))]

_AUDIO_MEDIA_TYPES = {
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "aac": "audio/aac",
    "amr": "audio/amr",
    "wav": "audio/wav",
    "weba": "audio/webm",
}


def _tenant(db: DbDep, principal: Principal) -> Tenant:
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Empresa não encontrada.")
    return tenant


def _load(db: DbDep, principal: Principal, conversation_id: uuid.UUID) -> Conversation:
    conversation = get_visible_conversation(db, principal, conversation_id)
    if conversation is None:
        raise NotFound("Conversa não encontrada.")
    return conversation


@router.post(
    "",
    response_model=ConversationIngested,
    status_code=201,
    summary="Enviar uma conversa por API",
)
def create(
    body: ConversationIn, request: Request, db: DbDep, principal: WriterDep
) -> ConversationIngested:
    """Para integrações (CRM, N8N, sistemas próprios).

    Idempotente: reenviar com o mesmo `external_id` (da conversa e/ou das mensagens) só
    acrescenta o que ainda não existe. A análise roda em segundo plano.
    """
    tenant = _tenant(db, principal)

    seller: Seller | None = None
    seller_id = body.seller_id
    if principal.is_seller_restricted:
        if principal.only_seller_id is None:
            raise Forbidden("Seu usuário ainda não está vinculado a um vendedor.")
        seller_id = principal.only_seller_id
    if seller_id is not None:
        seller = db.get(Seller, seller_id)
        if seller is None:
            raise NotFound("Vendedor não encontrado.")

    seller_author = (
        seller.display_name if seller else (body.seller_name or "").strip() or "Vendedor"
    )
    customer_author = (
        (body.customer_phone or "").strip()
        or (body.customer_name or "").strip()
        or (f"cliente:{body.external_id}" if body.external_id else "Cliente sem identificação")
    )
    if customer_author == seller_author:
        raise BadRequest("Vendedor e cliente não podem ter o mesmo nome.")

    participants = {
        seller_author: ParticipantInfo(
            seller_author,
            SenderRole.VENDEDOR,
            seller.id if seller else None,
            "alta",
            "informado pela API",
        ),
        customer_author: ParticipantInfo(
            customer_author, SenderRole.CLIENTE, None, "alta", "informado pela API"
        ),
    }
    zone = tenant_timezone(tenant)
    messages = [
        IncomingMessage(
            sent_at=to_utc(item.sent_at, zone),
            author=seller_author if item.sender == "vendedor" else customer_author,
            text=item.text.strip(),
            kind=item.kind if item.kind is not MessageKind.SISTEMA else MessageKind.OUTRO,
            external_id=item.external_id,
        )
        for item in body.messages
    ]
    result = ingest_conversation(
        db,
        tenant=tenant,
        source=ImportSource.API,
        participants=participants,
        messages=messages,
        playbook=(body.playbook or "").strip() or None,
        external_id=(body.external_id or "").strip() or None,
    )
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.IMPORT_CREATED,
        principal=principal,
        resource_type="conversation",
        resource_id=result.conversation.id,
        details={"origem": "api", "mensagens_novas": len(result.new_messages)},
        **request_meta(request),
    )
    db.commit()
    if result.new_messages or result.created:
        enqueue_conversation(result.conversation.id, principal.tenant_id)
        db.refresh(result.conversation)
    return ConversationIngested(
        conversation=ConversationOut.model_validate(result.conversation),
        created=result.created,
        new_messages=len(result.new_messages),
        duplicate_messages=result.duplicates,
    )


@router.get("", response_model=Page[ConversationOut], summary="Listar conversas")
def list_conversations(
    db: DbDep,
    principal: ReaderDep,
    page: Annotated[Pagination, Depends(pagination)],
    seller_id: uuid.UUID | None = None,
    status: ConversationStatus | None = None,
    source: ImportSource | None = None,
    date_from: Annotated[
        datetime | None, Query(description="Última mensagem a partir de (ISO 8601)")
    ] = None,
    date_to: Annotated[datetime | None, Query(description="Última mensagem até (ISO 8601)")] = None,
    needs_review: Annotated[
        bool | None,
        Query(description="Só conversas em que a identificação do vendedor não é certa"),
    ] = None,
) -> Page[ConversationOut]:
    filters: list[ColumnElement[bool]] = []
    if principal.is_seller_restricted:
        if principal.only_seller_id is None:
            return Page[ConversationOut](items=[], total=0, limit=page.limit, offset=page.offset)
        filters.append(Conversation.seller_id == principal.only_seller_id)
    elif seller_id is not None:
        filters.append(Conversation.seller_id == seller_id)
    if status is not None:
        filters.append(Conversation.status == status)
    if source is not None:
        filters.append(Conversation.source == source)
    tenant_zone = tenant_timezone(_tenant(db, principal))
    if date_from is not None:
        filters.append(Conversation.last_message_at >= to_utc(date_from, tenant_zone))
    if date_to is not None:
        filters.append(Conversation.last_message_at <= to_utc(date_to, tenant_zone))
    if needs_review is True:
        filters.append(Conversation.role_confidence != "alta")
    elif needs_review is False:
        filters.append(Conversation.role_confidence == "alta")

    rows, total = paginate(
        db,
        Conversation,
        filters=filters,
        order_by=[Conversation.last_message_at.desc().nulls_last(), Conversation.created_at.desc()],
        page=page,
    )
    return Page[ConversationOut](
        items=[ConversationOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail, summary="Ler uma conversa")
def get_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    db: DbDep,
    principal: ReaderDep,
    reveal: Annotated[
        bool,
        Query(description="Mostra o texto original e os nomes. Exige permissão e fica auditado."),
    ] = False,
) -> ConversationDetail:
    """Por padrão o texto vem com os dados pessoais mascarados."""
    conversation = _load(db, principal, conversation_id)
    tenant = _tenant(db, principal)
    if reveal and not can_reveal(principal, tenant):
        raise Forbidden("Você não tem permissão para ver os dados originais desta conversa.")

    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.sent_at, Message.position)
        ).all()
    )
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.CONVERSATION_REVEALED if reveal else AuditAction.CONVERSATION_VIEWED,
        principal=principal,
        resource_type="conversation",
        resource_id=conversation.id,
        **request_meta(request),
    )
    db.commit()

    base = ConversationOut.model_validate(conversation).model_dump()
    return ConversationDetail(
        **base,
        participants=participant_views(conversation, reveal=reveal),
        messages=message_views(conversation, messages, reveal=reveal),
        revealed=reveal,
        customer_name=conversation.customer_name if reveal else None,
        raw_purged=conversation.raw_purged_at is not None,
    )


@router.get(
    "/{conversation_id}/analysis", response_model=AnalysisOut, summary="Análise mais recente"
)
def get_analysis(conversation_id: uuid.UUID, db: DbDep, principal: ReaderDep) -> AnalysisOut:
    """Nota explicável, resumo, sugestão de próxima mensagem e alertas com a evidência."""
    conversation = _load(db, principal, conversation_id)
    analysis = current_analysis(db, conversation.id)
    if analysis is None:
        raise NotFound("Esta conversa ainda não foi analisada.")
    alerts = db.scalars(
        select(Alert)
        .where(Alert.conversation_id == conversation.id)
        .order_by(Alert.message_index.is_(None), Alert.message_index, Alert.type)
    ).all()
    details = analysis.details or {}
    return AnalysisOut(
        id=analysis.id,
        conversation_id=conversation.id,
        created_at=analysis.created_at,
        score=analysis.score,
        playbook=analysis.playbook,
        playbook_version=analysis.playbook_version,
        summary=analysis.summary,
        suggestion=analysis.suggestion,
        sentiment=analysis.sentiment,
        stage=analysis.stage,
        layers=list(analysis.layers or []),
        criteria=[CriterionOut(**c) for c in analysis.criteria or []],
        alerts=[alert_out(a) for a in alerts],
        objections=details.get("objections", []),
        requests=details.get("requests", []),
        metrics=details.get("metrics", {}),
        strengths=details.get("strengths", []),
        improvements=details.get("improvements", []),
        llm={
            "provider": analysis.llm_provider,
            "model": analysis.llm_model,
            "tokens_in": analysis.tokens_in,
            "tokens_out": analysis.tokens_out,
            "error": analysis.llm_error,
        },
        duration_ms=analysis.duration_ms,
    )


@router.patch("/{conversation_id}", response_model=ConversationOut, summary="Corrigir uma conversa")
def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    request: Request,
    db: DbDep,
    principal: WriterDep,
) -> ConversationOut:
    """Troca o vendedor, o playbook ou corrige quem é vendedor e quem é cliente.

    Qualquer mudança dispara uma nova análise.
    """
    conversation = _load(db, principal, conversation_id)
    if principal.is_seller_restricted and (body.seller_id or body.seller_participant):
        raise Forbidden("Só a gestão pode trocar o vendedor de uma conversa.")
    tenant = _tenant(db, principal)
    changes: list[str] = []

    if body.seller_participant is not None:
        try:
            set_seller_participant(db, conversation, tenant, body.seller_participant)
        except KeyError:
            raise BadRequest("Participante não encontrado nesta conversa.") from None
        changes.append("papeis")
    if body.seller_id is not None:
        seller = db.get(Seller, body.seller_id)
        if seller is None:
            raise NotFound("Vendedor não encontrado.")
        conversation.seller_id = seller.id
        entries = [dict(entry) for entry in conversation.participants or []]
        for entry in entries:
            if entry.get("role") == SenderRole.VENDEDOR.value:
                entry["seller_id"], entry["label"] = str(seller.id), seller.display_name
        conversation.participants = entries
        changes.append("vendedor")
    if body.playbook is not None and body.playbook.strip():
        conversation.playbook = body.playbook.strip()
        changes.append("playbook")

    if changes:
        conversation.status = ConversationStatus.PENDENTE
        record_audit(
            db,
            tenant_id=principal.tenant_id,
            action=AuditAction.CONVERSATION_REANALYZED,
            principal=principal,
            resource_type="conversation",
            resource_id=conversation.id,
            details={"mudancas": changes},
            **request_meta(request),
        )
        db.commit()
        enqueue_conversation(conversation.id, principal.tenant_id)
        db.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.post(
    "/{conversation_id}/reprocess",
    response_model=MessageResponse,
    status_code=202,
    summary="Reprocessar uma conversa",
)
def reprocess(
    conversation_id: uuid.UUID, request: Request, db: DbDep, principal: WriterDep
) -> MessageResponse:
    conversation = _load(db, principal, conversation_id)
    conversation.status = ConversationStatus.PENDENTE
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.CONVERSATION_REANALYZED,
        principal=principal,
        resource_type="conversation",
        resource_id=conversation.id,
        **request_meta(request),
    )
    db.commit()
    enqueue_conversation(conversation.id, principal.tenant_id)
    return MessageResponse(message="Conversa enviada para reprocessamento.")


@router.delete("/{conversation_id}", status_code=204, summary="Excluir uma conversa")
def delete(
    conversation_id: uuid.UUID,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: DeleterDep,
) -> Response:
    """Apaga a conversa, as mensagens, os áudios e as análises. Não há como desfazer."""
    conversation = _load(db, principal, conversation_id)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.CONVERSATION_DELETED,
        principal=principal,
        resource_type="conversation",
        resource_id=conversation.id,
        details={"mensagens": conversation.message_count},
        **request_meta(request),
    )
    delete_conversation(db, conversation, settings)
    db.commit()
    return Response(status_code=204)


@router.get(
    "/{conversation_id}/messages/{message_id}/audio",
    summary="Ouvir o áudio de uma mensagem",
    response_class=FileResponse,
    responses={200: {"content": {"audio/ogg": {}}}},
)
def get_audio(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: ReaderDep,
) -> FileResponse:
    """O áudio é dado pessoal sem máscara: exige a mesma permissão de "revelar"."""
    conversation = _load(db, principal, conversation_id)
    if not can_reveal(principal, _tenant(db, principal)):
        raise Forbidden("Você não tem permissão para ouvir os áudios originais.")
    message = db.get(Message, message_id)
    if message is None or message.conversation_id != conversation.id or not message.media_path:
        raise NotFound("Áudio não encontrado.")
    try:
        path = data_path(message.media_path, settings)
    except ValueError:
        raise NotFound("Áudio não encontrado.") from None
    if not path.is_file():
        raise NotFound("O áudio já foi removido pela política de retenção.")
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.CONVERSATION_REVEALED,
        principal=principal,
        resource_type="message_audio",
        resource_id=message.id,
        **request_meta(request),
    )
    db.commit()
    media_type = _AUDIO_MEDIA_TYPES.get(path.suffix.lstrip(".").lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})
