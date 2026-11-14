"""Importações, conversas e mensagens."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.db.base import Base, IdMixin, TenantScoped, TimestampMixin, utcnow
from radar.db.models.core import Seller
from radar.db.types import EncryptedText, JSONType, StrEnumType, UtcDateTime
from radar.taxonomy import (
    ConversationStatus,
    ImportSource,
    ImportStatus,
    MessageKind,
    SenderRole,
    TranscriptionStatus,
)


class Conversation(IdMixin, TimestampMixin, TenantScoped, Base):
    """Uma conversa entre um vendedor e um cliente (o fio inteiro, não um trecho)."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "external_id"),
        Index("ix_conversations_tenant_last", "tenant_id", "last_message_at"),
        Index("ix_conversations_tenant_fingerprint", "tenant_id", "fingerprint"),
        Index("ix_conversations_tenant_customer", "tenant_id", "customer_hash"),
    )

    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[ImportSource] = mapped_column(StrEnumType(ImportSource), nullable=False)
    #: Identificador da conversa no sistema de origem (API e webhooks).
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Hash dos participantes: reconhece o mesmo fio numa reimportação.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Pseudônimo estável do cliente ("Cliente 7F3A"): é o que o painel mostra por padrão.
    customer_label: Mapped[str] = mapped_column(String(80), nullable=False, default="Cliente")
    #: Nome ou telefone do cliente como veio na origem. Cifrado; só aparece com "revelar".
    customer_name: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    #: HMAC do identificador do cliente: localiza um titular sem guardar o dado em claro.
    customer_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    playbook: Mapped[str] = mapped_column(String(80), nullable=False, default="generico")
    status: Mapped[ConversationStatus] = mapped_column(
        StrEnumType(ConversationStatus), nullable=False, default=ConversationStatus.PENDENTE
    )
    status_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: ``[{key, role, seller_id, label, name_enc}]``, um por autor.
    participants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, nullable=False, default=list
    )
    #: ``alta`` | ``media`` | ``baixa``: quão certa é a identificação do vendedor.
    role_confidence: Mapped[str] = mapped_column(String(10), nullable=False, default="alta")
    warnings: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)

    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seller_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customer_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Quando a política de retenção apagou o texto bruto / os áudios.
    raw_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    media_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: Resumo da análise mais recente (para listar e filtrar sem juntar tabelas).
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    open_alerts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    seller: Mapped[Seller | None] = relationship(lazy="joined")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(Message.sent_at, Message.position)",
        lazy="select",
    )


class Message(IdMixin, TenantScoped, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "dedupe_hash"),
        Index("ix_messages_conversation_sent", "conversation_id", "sent_at", "position"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    sender_role: Mapped[SenderRole] = mapped_column(StrEnumType(SenderRole), nullable=False)
    #: Liga a mensagem a um item de ``Conversation.participants``.
    sender_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    kind: Mapped[MessageKind] = mapped_column(StrEnumType(MessageKind), nullable=False)

    #: Texto original (ou transcrição do áudio). Cifrado; apagado pela política de retenção.
    text_raw: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    #: Texto com os dados pessoais mascarados: é o que vai para o painel e para os LLMs.
    text_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``[{type, start, end}]`` sobre ``text_masked``, para destacar o que foi mascarado.
    pii_spans: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False, default=list)
    #: Reconhece a mesma mensagem numa reimportação (hora + autor + texto + ocorrência).
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    media_name: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    #: Caminho do áudio, relativo a ``RADAR_DATA_DIR``.
    media_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcription_status: Mapped[TranscriptionStatus] = mapped_column(
        StrEnumType(TranscriptionStatus),
        nullable=False,
        default=TranscriptionStatus.NAO_APLICAVEL,
    )
    transcription_model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Import(IdMixin, TimestampMixin, TenantScoped, Base):
    """Um arquivo enviado (ou uma chamada de API) e o que aconteceu com ele."""

    __tablename__ = "imports"
    __table_args__ = (Index("ix_imports_tenant_sha", "tenant_id", "file_sha256"),)

    source: Mapped[ImportSource] = mapped_column(StrEnumType(ImportSource), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(
        StrEnumType(ImportStatus), nullable=False, default=ImportStatus.PENDENTE
    )
    #: O nome do arquivo costuma trazer o nome do cliente, por isso é cifrado.
    filename: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="")
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: Onde o upload está guardado até ser processado (relativo a ``RADAR_DATA_DIR``).
    stored_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_label: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    #: Opções informadas no envio: vendedor, playbook…
    options: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Contagens do processamento: mensagens novas, repetidas, áudios, avisos.
    stats: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
