"""WhatsApp conectado (Evolution API) e pedidos de remoção de conversa."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.db.base import Base, IdMixin, TenantScoped, TimestampMixin, utcnow
from radar.db.models.core import Seller
from radar.db.types import StrEnumType, UtcDateTime
from radar.taxonomy import RemovalStatus, WhatsAppState


class WhatsAppConnection(IdMixin, TimestampMixin, TenantScoped, Base):
    """O número de WhatsApp de um vendedor, conectado como um "aparelho" (igual ao WhatsApp Web).

    A linha fica mesmo depois de desconectar: ao reconectar, as conversas continuam no mesmo fio,
    e a gestão vê desde quando o número está fora do ar.
    """

    __tablename__ = "whatsapp_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "seller_id"),)

    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False
    )
    #: Nome da instância na Evolution API (único na instalação inteira).
    instance_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    state: Mapped[WhatsAppState] = mapped_column(
        StrEnumType(WhatsAppState), nullable=False, default=WhatsAppState.DESCONECTADO
    )
    #: Só os 4 últimos dígitos do número conectado, para a gestão conferir qual é.
    phone_tail: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    connected_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    disconnected_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    seller: Mapped[Seller] = relationship(lazy="joined")


class WhatsAppIgnoredContact(IdMixin, TenantScoped, Base):
    """Contato que deixa de ser capturado (ex.: conversa pessoal cuja remoção a gestão aprovou).

    Guarda só o HMAC do contato, nunca o telefone.
    """

    __tablename__ = "whatsapp_ignored_contacts"
    __table_args__ = (UniqueConstraint("connection_id", "contact_hash"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("whatsapp_connections.id", ondelete="CASCADE"), nullable=False
    )
    contact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)


class RemovalRequest(IdMixin, TimestampMixin, TenantScoped, Base):
    """Pedido para tirar uma conversa do Radar. O vendedor pede; só a gestão aprova.

    Se o vendedor pudesse apagar sozinho, poderia esconder justamente as conversas ruins. O
    pedido fica guardado depois da decisão (a conversa, se aprovada, não).
    """

    __tablename__ = "removal_requests"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Retrato da conversa ("Cliente 7F3A, 23 mensagens"): continua legível depois da exclusão.
    conversation_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RemovalStatus] = mapped_column(
        StrEnumType(RemovalStatus), nullable=False, default=RemovalStatus.PENDENTE
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
