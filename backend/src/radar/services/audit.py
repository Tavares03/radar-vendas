"""Trilha de auditoria: quem viu ou alterou o quê."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from radar.auth.principal import Principal
from radar.db.models import AuditLog


class AuditAction:
    """Ações registradas. Texto estável: relatórios de compliance filtram por estes valores."""

    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    PASSWORD_CHANGED = "auth.password_changed"  # noqa: S105
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    SELLER_CREATED = "seller.created"
    SELLER_UPDATED = "seller.updated"
    SELLER_DELETED = "seller.deleted"
    TOKEN_CREATED = "api_token.created"  # noqa: S105
    TOKEN_REVOKED = "api_token.revoked"  # noqa: S105
    SETTINGS_UPDATED = "settings.updated"
    IMPORT_CREATED = "import.created"
    CONVERSATION_VIEWED = "conversation.viewed"
    CONVERSATION_REVEALED = "conversation.pii_revealed"
    CONVERSATION_DELETED = "conversation.deleted"
    CONVERSATION_REANALYZED = "conversation.reanalyzed"
    REMOVAL_REQUESTED = "conversation.removal_requested"
    REMOVAL_APPROVED = "conversation.removal_approved"
    REMOVAL_REJECTED = "conversation.removal_rejected"
    WHATSAPP_CONNECTED = "whatsapp.connected"
    WHATSAPP_DISCONNECTED = "whatsapp.disconnected"
    ALERT_REVIEWED = "alert.reviewed"
    PLAYBOOK_SAVED = "playbook.saved"
    PLAYBOOK_DELETED = "playbook.deleted"
    REPORT_EXPORTED = "report.exported"
    DATA_EXPORTED = "data.exported"
    SUBJECT_SEARCHED = "privacy.subject_searched"
    SUBJECT_EXPORTED = "privacy.subject_exported"
    SUBJECT_DELETED = "privacy.subject_deleted"
    RETENTION_RUN = "privacy.retention_run"
    WEBHOOK_SAVED = "webhook.saved"
    WEBHOOK_DELETED = "webhook.deleted"
    CHANNEL_SAVED = "notification_channel.saved"
    CHANNEL_DELETED = "notification_channel.deleted"
    INTEGRATION_SAVED = "integration.saved"
    INTEGRATION_DELETED = "integration.deleted"
    SEARCH = "search.query"


def record_audit(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    action: str,
    principal: Principal | None = None,
    actor_label: str | None = None,
    resource_type: str = "",
    resource_id: str | uuid.UUID = "",
    ip: str = "",
    user_agent: str = "",
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Adiciona um registro de auditoria à transação atual (quem chama faz o commit)."""
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=principal.user_id if principal else None,
        actor_token_id=principal.token_id if principal else None,
        actor_label=actor_label or (principal.label if principal else "sistema"),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        ip=ip[:64],
        user_agent=user_agent[:500],
        details=details or {},
    )
    db.add(entry)
    return entry
