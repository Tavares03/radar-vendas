"""Etapa de privacidade do pipeline: mascara as mensagens e alimenta o índice de titulares."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from radar.config import Settings
from radar.db.models import PARTICIPANT_ENTRY, Conversation, Message, PiiIndexEntry, Tenant
from radar.logs import get_logger
from radar.privacy.crypto import DecryptionError, decrypt_text, subject_hash
from radar.privacy.detector import get_pii_detector
from radar.privacy.masking import MaskedText
from radar.taxonomy import SenderRole

log = get_logger(__name__)

#: Mensagens mascaradas por lote (o NER processa o lote de uma vez).
BATCH_SIZE = 64


def participant_names(conversation: Conversation) -> list[str]:
    """Nomes (como vieram na origem) de todos os participantes, para mascarar no texto."""
    names = []
    for entry in conversation.participants or []:
        encrypted = entry.get("name_enc")
        if not encrypted:
            continue
        try:
            names.append(decrypt_text(encrypted))
        except DecryptionError:
            log.warning("nome_de_participante_ilegivel", conversation_id=str(conversation.id))
    return names


def _index_entries(
    tenant_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID, masked: MaskedText
) -> list[PiiIndexEntry]:
    seen: set[tuple[str, str]] = set()
    entries = []
    for span in masked.found:
        key = (subject_hash(tenant_id, span.text), span.type.value)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            PiiIndexEntry(
                tenant_id=tenant_id,
                subject_hash=key[0],
                pii_type=key[1],
                conversation_id=conversation_id,
                message_id=message_id,
            )
        )
    return entries


def index_participants(db: Session, conversation: Conversation) -> None:
    """Refaz as entradas de participante (clientes) da conversa no índice de titulares."""
    db.execute(
        delete(PiiIndexEntry).where(
            PiiIndexEntry.conversation_id == conversation.id,
            PiiIndexEntry.message_id.is_(None),
        )
    )
    keys = {
        entry["key"]
        for entry in conversation.participants or []
        if entry.get("key") and entry.get("role") != SenderRole.VENDEDOR.value
    }
    for key in sorted(keys):
        db.add(
            PiiIndexEntry(
                tenant_id=conversation.tenant_id,
                subject_hash=key,
                pii_type=PARTICIPANT_ENTRY,
                conversation_id=conversation.id,
                message_id=None,
            )
        )


def mask_messages(
    db: Session,
    conversation: Conversation,
    messages: Sequence[Message],
    *,
    mask_names: bool,
) -> int:
    """Mascara as mensagens informadas e atualiza o índice. Devolve quantas foram mascaradas."""
    detector = get_pii_detector()
    names = participant_names(conversation)
    done = 0
    for offset in range(0, len(messages), BATCH_SIZE):
        batch = list(messages[offset : offset + BATCH_SIZE])
        results = detector.mask_many(
            [message.text_raw or "" for message in batch],
            known_names=names,
            mask_names=mask_names,
        )
        db.execute(delete(PiiIndexEntry).where(PiiIndexEntry.message_id.in_([m.id for m in batch])))
        for message, masked in zip(batch, results, strict=True):
            message.text_masked = masked.text
            message.pii_spans = masked.span_dicts()
            db.add_all(_index_entries(conversation.tenant_id, conversation.id, message.id, masked))
        db.flush()
        done += len(batch)
    return done


def privacy_stage(db: Session, conversation: Conversation, settings: Settings) -> None:
    """Mascara toda mensagem que tem texto original e ainda não tem máscara."""
    tenant = db.get(Tenant, conversation.tenant_id)
    mask_names = tenant.get_settings().mask_person_names if tenant else True
    pending = db.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.text_masked.is_(None),
            Message.text_raw.is_not(None),
        )
        .order_by(Message.sent_at, Message.position)
    ).all()
    masked = mask_messages(db, conversation, pending, mask_names=mask_names)
    index_participants(db, conversation)
    if masked:
        log.info(
            "mensagens_mascaradas",
            conversation_id=str(conversation.id),
            mensagens=masked,
            camadas=",".join(get_pii_detector().layers),
        )
