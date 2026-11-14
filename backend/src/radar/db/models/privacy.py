"""Índice de titulares: localiza os dados de uma pessoa sem guardar o dado em claro."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from radar.db.base import Base, IdMixin, TenantScoped, utcnow
from radar.db.types import UtcDateTime

#: ``pii_type`` das entradas que representam um participante da conversa (não um trecho de texto).
PARTICIPANT_ENTRY = "PARTICIPANTE"


class PiiIndexEntry(IdMixin, TenantScoped, Base):
    """Um identificador (CPF, telefone, e-mail, nome…) visto numa conversa ou mensagem.

    Guarda só o HMAC por empresa (:func:`radar.privacy.crypto.subject_hash`): com o CPF em mãos dá
    para achar todas as conversas do titular; com o banco em mãos, não dá para recuperar o CPF.
    """

    __tablename__ = "pii_index"
    __table_args__ = (Index("ix_pii_index_tenant_subject", "tenant_id", "subject_hash"),)

    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Um :class:`~radar.taxonomy.PiiType` ou :data:`PARTICIPANT_ENTRY`.
    pii_type: Mapped[str] = mapped_column(String(40), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Vazio nas entradas de participante.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
