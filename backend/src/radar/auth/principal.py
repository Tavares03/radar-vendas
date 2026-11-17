"""Quem está fazendo a requisição e o que pode fazer."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from radar.taxonomy import Role


class Permission(StrEnum):
    CONVERSATIONS_READ = "conversations:read"
    CONVERSATIONS_WRITE = "conversations:write"
    CONVERSATIONS_DELETE = "conversations:delete"
    PII_REVEAL = "pii:reveal"
    ALERTS_READ = "alerts:read"
    ALERTS_REVIEW = "alerts:review"
    ANALYTICS_READ = "analytics:read"
    COACH_USE = "coach:use"
    PLAYBOOKS_READ = "playbooks:read"
    PLAYBOOKS_WRITE = "playbooks:write"
    SELLERS_MANAGE = "sellers:manage"
    USERS_MANAGE = "users:manage"
    SETTINGS_MANAGE = "settings:manage"
    AUDIT_READ = "audit:read"
    PRIVACY_MANAGE = "privacy:manage"
    REPORTS_EXPORT = "reports:export"
    #: Ver e desconectar o WhatsApp de toda a equipe (o vendedor só conecta o próprio).
    WHATSAPP_MANAGE = "whatsapp:manage"


P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.GESTOR: frozenset(
        {
            P.CONVERSATIONS_READ,
            P.CONVERSATIONS_WRITE,
            P.CONVERSATIONS_DELETE,
            P.PII_REVEAL,
            P.ALERTS_READ,
            P.ALERTS_REVIEW,
            P.ANALYTICS_READ,
            P.COACH_USE,
            P.PLAYBOOKS_READ,
            P.PLAYBOOKS_WRITE,
            P.SELLERS_MANAGE,
            P.REPORTS_EXPORT,
            P.WHATSAPP_MANAGE,
        }
    ),
    # O vendedor enxerga só as próprias conversas e alertas (ver Principal.only_seller_id).
    Role.VENDEDOR: frozenset(
        {
            P.CONVERSATIONS_READ,
            P.CONVERSATIONS_WRITE,
            P.ALERTS_READ,
            P.COACH_USE,
            P.PLAYBOOKS_READ,
        }
    ),
    # O auditor lê tudo e não altera nada.
    Role.AUDITOR: frozenset(
        {
            P.CONVERSATIONS_READ,
            P.PII_REVEAL,
            P.ALERTS_READ,
            P.ANALYTICS_READ,
            P.PLAYBOOKS_READ,
            P.AUDIT_READ,
            P.REPORTS_EXPORT,
        }
    ),
}


class TokenScope(StrEnum):
    INGEST = "ingest"
    READ = "read"


SCOPE_PERMISSIONS: dict[TokenScope, frozenset[Permission]] = {
    TokenScope.INGEST: frozenset({P.CONVERSATIONS_WRITE}),
    TokenScope.READ: frozenset(
        {P.CONVERSATIONS_READ, P.ALERTS_READ, P.ANALYTICS_READ, P.PLAYBOOKS_READ}
    ),
}


def permissions_for_scopes(scopes: list[str]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for scope in scopes:
        try:
            granted |= SCOPE_PERMISSIONS[TokenScope(scope)]
        except ValueError:
            continue
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: uuid.UUID
    permissions: frozenset[Permission]
    label: str
    role: Role | None = None
    user_id: uuid.UUID | None = None
    token_id: uuid.UUID | None = None
    seller_id: uuid.UUID | None = None

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def is_seller_restricted(self) -> bool:
        """Verdadeiro para o papel vendedor: a visão fica limitada às próprias conversas."""
        return self.role == Role.VENDEDOR

    @property
    def only_seller_id(self) -> uuid.UUID | None:
        """Vendedor ao qual a visão está limitada (``None`` se o vínculo ainda não existe)."""
        return self.seller_id if self.is_seller_restricted else None
