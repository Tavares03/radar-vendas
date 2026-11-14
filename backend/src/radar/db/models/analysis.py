"""Análises, alertas, métricas por etapa do pipeline e playbooks próprios das empresas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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
from radar.db.models.conversations import Conversation
from radar.db.models.core import User
from radar.db.types import JSONType, StrEnumType, UtcDateTime
from radar.taxonomy import AlertStatus


class Analysis(IdMixin, TenantScoped, Base):
    """Resultado de uma análise. Reanalisar cria outra; só a mais nova fica ``is_current``."""

    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_conversation_current", "conversation_id", "is_current"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    playbook: Mapped[str] = mapped_column(String(80), nullable=False)
    playbook_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggestion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    layers: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False, default=list)
    #: Objeções, pedidos, métricas, pontos fortes/fracos, rótulos e o que foi descartado.
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    llm_provider: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    llm_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    llm_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Alert(IdMixin, TimestampMixin, TenantScoped, Base):
    """Um risco, oportunidade perdida ou problema de qualidade, com a evidência e quem viu."""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("conversation_id", "fingerprint"),
        Index("ix_alerts_tenant_status_severity", "tenant_id", "status", "severity"),
        Index("ix_alerts_tenant_created", "tenant_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Identifica o mesmo alerta entre reanálises (tipo + mensagem), para manter a revisão.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    message_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Trecho da mensagem (mascarado) que é a evidência.
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sources: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    contested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[AlertStatus] = mapped_column(
        StrEnumType(AlertStatus), nullable=False, default=AlertStatus.ABERTO
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    conversation: Mapped[Conversation] = relationship(lazy="joined")
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_user_id], lazy="joined")


class StageMetric(IdMixin, TenantScoped, Base):
    """Uma execução de uma etapa do pipeline: tempo, tokens e se falhou."""

    __tablename__ = "stage_metrics"
    __table_args__ = (Index("ix_stage_metrics_tenant_created", "tenant_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TenantPlaybook(IdMixin, TimestampMixin, TenantScoped, Base):
    """Playbook escrito pela empresa (pelo painel ou por arquivo), em YAML."""

    __tablename__ = "playbooks"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
