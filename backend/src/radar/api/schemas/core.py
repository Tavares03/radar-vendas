"""Schemas de autenticação, empresa, usuários, vendedores, tokens e auditoria."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from radar.api.schemas.common import ApiModel
from radar.auth.passwords import MIN_PASSWORD_LENGTH
from radar.auth.principal import TokenScope
from radar.taxonomy import Role
from radar.tenant_settings import TenantSettings

Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)


# ------------------------------------------------------------------ empresa
class TenantOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    default_playbook: str
    settings: TenantSettings

    @field_validator("settings", mode="before")
    @classmethod
    def _settings(cls, value: Any) -> Any:
        return value or {}


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=200)
    default_playbook: str | None = Field(default=None, min_length=1, max_length=80)
    settings: TenantSettings | None = None


# ------------------------------------------------------------------ autenticação
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class SignupIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Password


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: Role
    seller_id: uuid.UUID | None
    permissions: list[str]
    tenant: TenantOut


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_at: datetime
    user: MeOut


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Password


# ------------------------------------------------------------------ vendedores
class SellerOut(ApiModel):
    id: uuid.UUID
    display_name: str
    aliases: list[str]
    is_active: bool
    created_at: datetime


class SellerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class SellerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = Field(default=None, max_length=50)
    is_active: bool | None = None


# ------------------------------------------------------------------ usuários
class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    name: str
    role: Role
    seller_id: uuid.UUID | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str = Field(min_length=2, max_length=200)
    role: Role
    password: str = Password
    seller_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=200)
    role: Role | None = None
    seller_id: uuid.UUID | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=200)


# ------------------------------------------------------------------ tokens de API
class ApiTokenOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    scopes: list[TokenScope] = Field(min_length=1)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiTokenCreated(ApiTokenOut):
    #: Valor completo do token. Aparece só nesta resposta; guarde-o agora.
    token: str


# ------------------------------------------------------------------ auditoria
class AuditLogOut(ApiModel):
    id: uuid.UUID
    created_at: datetime
    actor_label: str
    actor_user_id: uuid.UUID | None
    actor_token_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str
    ip: str
    details: dict[str, Any]
