"""Pedidos de remoção de conversa: o vendedor pede, só a gestão decide.

Se o vendedor pudesse apagar sozinho, poderia esconder justamente as conversas ruins. Por isso
ele só pede (com motivo); a conversa continua visível e analisada até a gestão decidir. Aprovar
apaga a conversa (e, se ela veio do WhatsApp conectado, para de capturar aquele contato); recusar
mantém tudo. O pedido e a decisão ficam guardados e na trilha de auditoria.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.auth.principal import Principal
from radar.config import Settings
from radar.db.models import Conversation, RemovalRequest
from radar.integrations.whatsapp import ignore_contact
from radar.services.conversations import delete_conversation
from radar.taxonomy import RemovalStatus
from radar.textutil import plural


class RemovalError(ValueError):
    """Regra do fluxo de remoção violada (pedido repetido, já decidido…)."""


def conversation_label(conversation: Conversation) -> str:
    seller = (
        conversation.seller.display_name if conversation.seller else "vendedor não identificado"
    )
    count = plural(conversation.message_count, "mensagem", "mensagens")
    return f"{conversation.customer_label} com {seller}, {count}"[:200]


def pending_for(db: Session, conversation_id: uuid.UUID) -> RemovalRequest | None:
    return db.scalar(
        select(RemovalRequest).where(
            RemovalRequest.conversation_id == conversation_id,
            RemovalRequest.status == RemovalStatus.PENDENTE,
        )
    )


def request_removal(
    db: Session, *, principal: Principal, conversation: Conversation, reason: str
) -> RemovalRequest:
    if pending_for(db, conversation.id) is not None:
        raise RemovalError("Já existe um pedido de remoção desta conversa esperando a gestão.")
    request = RemovalRequest(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        conversation_label=conversation_label(conversation),
        seller_id=conversation.seller_id,
        requested_by_user_id=principal.user_id,
        reason=reason.strip(),
        status=RemovalStatus.PENDENTE,
    )
    db.add(request)
    db.flush()
    return request


def decide(
    db: Session,
    *,
    principal: Principal,
    request: RemovalRequest,
    approve: bool,
    note: str,
    stop_capturing: bool,
    settings: Settings,
) -> bool:
    """Aprova ou recusa. Devolve se o contato deixou de ser capturado (só na aprovação)."""
    if request.status is not RemovalStatus.PENDENTE:
        raise RemovalError("Este pedido já foi decidido.")
    request.status = RemovalStatus.APROVADO if approve else RemovalStatus.RECUSADO
    request.decided_by_user_id = principal.user_id
    request.decided_at = datetime.now(UTC)
    request.decision_note = note.strip()
    ignored = False
    if approve and request.conversation_id is not None:
        conversation = db.get(Conversation, request.conversation_id)
        request.conversation_id = None
        if conversation is not None:
            ignored = stop_capturing and ignore_contact(db, conversation)
            delete_conversation(db, conversation, settings)
    db.flush()
    return ignored


def close_pending_on_delete(db: Session, conversation_id: uuid.UUID, principal: Principal) -> None:
    """A gestão excluiu a conversa direto: o pedido pendente dela fica como aprovado."""
    for request in db.scalars(
        select(RemovalRequest).where(
            RemovalRequest.conversation_id == conversation_id,
            RemovalRequest.status == RemovalStatus.PENDENTE,
        )
    ):
        request.status = RemovalStatus.APROVADO
        request.decided_by_user_id = principal.user_id
        request.decided_at = datetime.now(UTC)
        request.decision_note = "Conversa excluída diretamente pela gestão."
        request.conversation_id = None
    db.flush()
