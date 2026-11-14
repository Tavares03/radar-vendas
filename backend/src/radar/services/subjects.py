"""Direitos do titular (LGPD, art. 18): localizar, exportar e excluir os dados de uma pessoa.

O titular é encontrado pelo HMAC dos identificadores informados (nome, telefone, CPF, e-mail…),
sem que o banco precise guardar nenhum deles em claro. Duas relações possíveis com uma conversa:

- ``participante``: a pessoa é o cliente da conversa (nome ou telefone de quem escreveu);
- ``mencionado``: um dado dela aparece no texto de uma conversa de outra pessoa.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from radar.config import Settings
from radar.db.models import PARTICIPANT_ENTRY, Conversation, Message, PiiIndexEntry, Tenant
from radar.privacy.crypto import subject_hash
from radar.services.conversations import delete_conversation
from radar.services.privacy import mask_messages

Relation = Literal["participante", "mencionado"]


@dataclass(slots=True)
class SubjectMatch:
    conversation_id: uuid.UUID
    relation: Relation
    #: Mensagens com dado do titular → tipos encontrados nelas.
    mentions: dict[uuid.UUID, set[str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SubjectDeletion:
    conversations_deleted: int
    messages_redacted: int


def subject_hashes(tenant_id: uuid.UUID, identifiers: Iterable[str]) -> set[str]:
    return {subject_hash(tenant_id, value) for value in identifiers if value.strip()}


def find_subject(
    db: Session, tenant_id: uuid.UUID, identifiers: Sequence[str]
) -> dict[uuid.UUID, SubjectMatch]:
    """Conversas da empresa ligadas ao titular. A sessão precisa estar no escopo da empresa."""
    hashes = subject_hashes(tenant_id, identifiers)
    if not hashes:
        return {}
    matches: dict[uuid.UUID, SubjectMatch] = {}
    for conversation_id in db.scalars(
        select(Conversation.id).where(
            Conversation.tenant_id == tenant_id, Conversation.customer_hash.in_(hashes)
        )
    ):
        matches[conversation_id] = SubjectMatch(conversation_id, "participante")
    entries = db.execute(
        select(
            PiiIndexEntry.conversation_id, PiiIndexEntry.message_id, PiiIndexEntry.pii_type
        ).where(PiiIndexEntry.tenant_id == tenant_id, PiiIndexEntry.subject_hash.in_(hashes))
    ).all()
    for conversation_id, message_id, pii_type in entries:
        match = matches.setdefault(conversation_id, SubjectMatch(conversation_id, "mencionado"))
        if pii_type == PARTICIPANT_ENTRY:
            match.relation = "participante"
        elif message_id is not None:
            match.mentions.setdefault(message_id, set()).add(pii_type)
    return matches


def _message_export(message: Message, *, own: bool, types: set[str]) -> dict[str, Any]:
    if own and message.text_raw is not None:
        text, original = message.text_raw, True
    else:
        text, original = message.text_masked or "", False
    item: dict[str, Any] = {
        "enviada_em": message.sent_at.isoformat(),
        "autor": message.sender_role.value,
        "tipo": message.kind.value,
        "texto": text,
        "texto_original": original,
    }
    if types:
        item["dados_do_titular"] = sorted(types)
    return item


def export_subject(
    db: Session, tenant: Tenant, matches: dict[uuid.UUID, SubjectMatch]
) -> dict[str, Any]:
    """Relatório dos dados do titular (direito de acesso), pronto para virar JSON.

    Conversas em que ele participa vão inteiras e com o texto original (ele já conhece esse
    conteúdo). Conversas de terceiros só entram com as mensagens que têm o dado dele, mascaradas:
    o resto do texto pode ter dados de outras pessoas.
    """
    conversations = []
    for match in sorted(matches.values(), key=lambda m: str(m.conversation_id)):
        conversation = db.get(Conversation, match.conversation_id)
        if conversation is None:
            continue
        query = select(Message).where(Message.conversation_id == conversation.id)
        own = match.relation == "participante"
        if not own:
            query = query.where(Message.id.in_(list(match.mentions)))
        messages = db.scalars(query.order_by(Message.sent_at, Message.position)).all()
        conversations.append(
            {
                "id": str(conversation.id),
                "relacao": match.relation,
                "origem": conversation.source.value,
                "vendedor": conversation.seller.display_name if conversation.seller else None,
                "inicio": conversation.started_at.isoformat() if conversation.started_at else None,
                "fim": (
                    conversation.last_message_at.isoformat()
                    if conversation.last_message_at
                    else None
                ),
                "texto_original_apagado_pela_retencao": conversation.raw_purged_at is not None,
                "mensagens": [
                    _message_export(m, own=own, types=match.mentions.get(m.id, set()))
                    for m in messages
                ],
            }
        )
    return {
        "gerado_em": datetime.now(UTC).isoformat(),
        "controlador": tenant.name,
        "conversas": conversations,
        "observacoes": (
            "Conversas em que o titular participa trazem o texto original, quando ainda não "
            "apagado pela política de retenção. Conversas de terceiros trazem só as mensagens "
            "com dados do titular, com os dados pessoais mascarados."
        ),
    }


def delete_subject(
    db: Session,
    tenant: Tenant,
    identifiers: Sequence[str],
    matches: dict[uuid.UUID, SubjectMatch],
    settings: Settings,
) -> SubjectDeletion:
    """Exclui as conversas do titular e apaga o original das mensagens que o mencionam.

    Quem chama faz o commit. Antes de excluir, a empresa precisa avaliar as exceções do art. 16
    da LGPD (obrigação legal, exercício de direitos em processo…).
    """
    hashes = subject_hashes(tenant.id, identifiers)
    deleted = redacted = 0
    mention_ids: list[uuid.UUID] = []
    for match in matches.values():
        conversation = db.get(Conversation, match.conversation_id)
        if conversation is None:
            continue
        if match.relation == "participante":
            delete_conversation(db, conversation, settings)
            deleted += 1
            continue
        messages = db.scalars(select(Message).where(Message.id.in_(list(match.mentions)))).all()
        unmasked = [m for m in messages if m.text_masked is None and m.text_raw is not None]
        if unmasked:
            mask_messages(
                db, conversation, unmasked, mask_names=tenant.get_settings().mask_person_names
            )
        mention_ids.extend(m.id for m in messages)
    if mention_ids:
        db.execute(
            update(Message)
            .where(Message.tenant_id == tenant.id, Message.id.in_(mention_ids))
            .values(text_raw=None, media_name=None),
            execution_options={"synchronize_session": False},
        )
        redacted = len(mention_ids)
    db.execute(
        delete(PiiIndexEntry).where(
            PiiIndexEntry.tenant_id == tenant.id, PiiIndexEntry.subject_hash.in_(hashes)
        )
    )
    db.flush()
    db.expire_all()
    return SubjectDeletion(conversations_deleted=deleted, messages_redacted=redacted)
