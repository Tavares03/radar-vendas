"""Empresa, usuários, vendedores, tokens de API e trilha de auditoria."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radar.db.base import Base, IdMixin, TenantScoped, TimestampMixin, utcnow
from radar.db.types import JSONType, StrEnumType, UtcDateTime
from radar.taxonomy import Role
from radar.tenant_settings import TenantSettings, load_tenant_settings


class Tenant(IdMixin, TimestampMixin, Base):
    """Uma empresa. Todos os outros dados pertencem a exatamente uma."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    default_playbook: Mapped[str] = mapped_column(String(80), nullable=False, default="generico")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def get_settings(self) -> TenantSettings:
        return load_tenant_settings(self.settings)

    def set_settings(self, value: TenantSettings) -> None:
        self.settings = value.model_dump(mode="json")


class Seller(IdMixin, TimestampMixin, TenantScoped, Base):
    """Um vendedor, tenha ou não login no painel."""

    __tablename__ = "sellers"
    __table_args__ = (UniqueConstraint("tenant_id", "display_name"),)

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Nomes e telefones com que o vendedor aparece nos exports (para identificá-lo).
    aliases: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class User(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(StrEnumType(Role), nullable=False)
    #: Para o papel ``vendedor``: quais conversas ele pode ver.
    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Sobe a cada troca de senha: sessões emitidas com a versão anterior deixam de valer.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    seller: Mapped[Seller | None] = relationship(lazy="joined")


class ApiToken(IdMixin, TimestampMixin, TenantScoped, Base):
    """Token de integração. Só o hash é guardado; o valor aparece uma única vez, na criação."""

    __tablename__ = "api_tokens"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AuditLog(IdMixin, TenantScoped, Base):
    """Quem fez o quê, e quando. Só inserção: a API não altera nem apaga registros."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_logs_resource", "tenant_id", "resource_type", "resource_id"),
    )

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("api_tokens.id", ondelete="SET NULL"), nullable=True
    )
    #: Rótulo do autor no momento da ação (sobrevive à exclusão do usuário).
    actor_label: Mapped[str] = mapped_column(String(320), nullable=False, default="sistema")
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
