"""Leitura e manutenção de conversas: o que pode ser mostrado, correção de papéis, exclusão."""

from __future__ import annotations

import shutil
import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from radar.auth.principal import Permission, Principal
from radar.config import Settings
from radar.db.models import Conversation, Import, Message, Seller, Tenant
from radar.logs import get_logger
from radar.privacy.crypto import DecryptionError, decrypt_text, pseudonym, subject_hash
from radar.taxonomy import SenderRole

log = get_logger(__name__)


def can_reveal(principal: Principal, tenant: Tenant) -> bool:
    """Quem pode ver o texto original e os nomes: permissão + papéis liberados pela empresa."""
    if not principal.can(Permission.PII_REVEAL):
        return False
    if principal.role is None:
        return False  # tokens de API nunca recebem dado pessoal em claro
    return principal.role in tenant.get_settings().reveal_roles


def get_visible_conversation(
    db: Session, principal: Principal, conversation_id: uuid.UUID
) -> Conversation | None:
    """A conversa, se existir nesta empresa e o usuário puder vê-la."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        return None
    if principal.is_seller_restricted and conversation.seller_id != principal.only_seller_id:
        return None
    return conversation


def participant_views(conversation: Conversation, *, reveal: bool) -> list[dict[str, Any]]:
    views = []
    for entry in conversation.participants or []:
        name: str | None = None
        if reveal and entry.get("name_enc"):
            try:
                name = decrypt_text(entry["name_enc"])
            except DecryptionError:
                name = None
        views.append(
            {
                "key": entry.get("key", ""),
                "role": entry.get("role", SenderRole.OUTRO.value),
                "label": entry.get("label", ""),
                "seller_id": entry.get("seller_id"),
                "confidence": entry.get("confidence", "alta"),
                "reason": entry.get("reason", ""),
                "name": name,
            }
        )
    return views


def message_views(
    conversation: Conversation, messages: list[Message], *, reveal: bool
) -> list[dict[str, Any]]:
    """Mensagens no formato da API, com o texto que este leitor pode ver."""
    labels = {entry.get("key"): entry.get("label", "") for entry in conversation.participants or []}
    views = []
    for message in messages:
        raw = message.text_raw
        if reveal and raw is not None:
            text, available, revealed, spans = raw, True, True, []
        elif message.text_masked is not None:
            text, available, revealed = message.text_masked, True, False
            spans = list(message.pii_spans or [])
        elif raw is None or raw == "":
            # Mídia sem legenda, mensagem apagada ou texto já removido pela retenção.
            text, available, revealed, spans = "", True, False, []
        else:
            text, available, revealed, spans = "", False, False, []
        views.append(
            {
                "id": message.id,
                "position": message.position,
                "sent_at": message.sent_at,
                "sender_role": message.sender_role,
                "sender_key": message.sender_key,
                "sender_label": labels.get(message.sender_key) or message.sender_role.value,
                "kind": message.kind,
                "text": text,
                "text_available": available,
                "revealed": revealed,
                "pii_spans": spans,
                "has_audio": bool(message.media_path),
                "audio_seconds": message.media_seconds,
                "transcription_status": message.transcription_status,
                "edited": message.edited,
                "revoked": message.revoked_at is not None,
            }
        )
    return views


def set_seller_participant(
    db: Session, conversation: Conversation, tenant: Tenant, key: str
) -> bool:
    """Define qual participante é o vendedor (os demais viram clientes). Devolve se mudou algo."""
    entries = [dict(entry) for entry in conversation.participants or []]
    if key not in {entry.get("key") for entry in entries}:
        raise KeyError(key)

    changed = False
    seller: Seller | None = None
    customer_name: str | None = None
    for entry in entries:
        new_role = SenderRole.VENDEDOR if entry.get("key") == key else SenderRole.CLIENTE
        try:
            name = decrypt_text(entry.get("name_enc", "")) if entry.get("name_enc") else ""
        except DecryptionError:
            name = ""
        if entry.get("role") != new_role.value:
            changed = True
            db.execute(
                update(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.sender_key == entry.get("key"),
                )
                .values(sender_role=new_role)
            )
        entry["role"] = new_role.value
        entry["confidence"] = "alta"
        entry["reason"] = "confirmado no painel"
        if new_role is SenderRole.VENDEDOR:
            display = name.strip()[:200] or "Vendedor"
            seller = db.scalar(select(Seller).where(Seller.display_name == display))
            if seller is None:
                seller = Seller(tenant_id=tenant.id, display_name=display, aliases=[])
                db.add(seller)
                db.flush()
            entry["label"] = seller.display_name
            entry["seller_id"] = str(seller.id)
        else:
            entry["label"] = pseudonym(tenant.id, name) if name else "Cliente"
            entry["seller_id"] = None
            customer_name = customer_name or name or None

    conversation.participants = entries
    conversation.role_confidence = "alta"
    if seller is not None:
        conversation.seller_id = seller.id
    conversation.customer_name = customer_name
    conversation.customer_label = (
        pseudonym(tenant.id, customer_name) if customer_name else "Cliente"
    )
    conversation.customer_hash = subject_hash(tenant.id, customer_name) if customer_name else None
    db.flush()
    _recount_roles(db, conversation)
    return changed


def _recount_roles(db: Session, conversation: Conversation) -> None:
    from radar.services.ingestion import _refresh_counters

    _refresh_counters(db, conversation)


def delete_conversation(db: Session, conversation: Conversation, settings: Settings) -> None:
    """Apaga a conversa, as mensagens, os áudios em disco e o registro das importações."""
    media_folder = settings.media_dir / str(conversation.tenant_id) / str(conversation.id)
    db.execute(delete(Import).where(Import.conversation_id == conversation.id))
    db.execute(delete(Message).where(Message.conversation_id == conversation.id))
    db.delete(conversation)
    db.flush()
    if media_folder.exists():
        shutil.rmtree(media_folder, ignore_errors=True)
