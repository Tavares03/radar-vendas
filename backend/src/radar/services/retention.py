"""Política de retenção (LGPD: minimização e eliminação ao fim do tratamento).

Por empresa, em dias contados a partir de quando o Radar *recebeu* o dado (não da data da
mensagem: importar um export antigo não pode apagar o original no mesmo instante):

- ``retention_raw_days``: apaga o texto original das mensagens (e o nome dos anexos). O texto
  mascarado e a análise ficam. Mensagem ainda sem máscara é mascarada antes, para não sumir.
- ``retention_media_days``: apaga os arquivos de áudio. A transcrição segue a regra do texto.
- ``retention_conversation_days``: apaga a conversa inteira (mensagens, áudios, análises) quando
  nada novo chegou nela no período.

Zero desliga cada regra. Roda pelo agendador, pela CLI (``radar retention-run``) e pela API.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session

from radar.config import Settings
from radar.db.models import Conversation, Message, Tenant
from radar.db.session import session_scope
from radar.logs import get_logger
from radar.services.audit import AuditAction, record_audit
from radar.services.conversations import delete_conversation
from radar.services.ingestion import data_path
from radar.services.privacy import mask_messages

log = get_logger(__name__)

_CHUNK = 500


@dataclass(slots=True)
class RetentionReport:
    tenant_id: uuid.UUID
    dry_run: bool = False
    raw_messages_purged: int = 0
    masked_before_purge: int = 0
    media_files_deleted: int = 0
    conversations_deleted: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.raw_messages_purged or self.media_files_deleted or self.conversations_deleted
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tenant_id"] = str(self.tenant_id)
        return data


def _chunks[T](items: Sequence[T]) -> list[Sequence[T]]:
    return [items[i : i + _CHUNK] for i in range(0, len(items), _CHUNK)]


def _purge_raw(
    db: Session, tenant: Tenant, cutoff: datetime, now: datetime, report: RetentionReport
) -> None:
    rows = db.execute(
        select(Message.id, Message.conversation_id).where(
            Message.tenant_id == tenant.id,
            Message.created_at < cutoff,
            or_(Message.text_raw.is_not(None), Message.media_name.is_not(None)),
        )
    ).all()
    report.raw_messages_purged = len(rows)
    if not rows:
        return

    # Sem máscara, a mensagem perderia o texto de vez: mascara antes de apagar o original.
    unmasked = db.scalars(
        select(Message).where(
            Message.id.in_([row.id for row in rows]),
            Message.text_masked.is_(None),
            Message.text_raw.is_not(None),
        )
    ).all()
    report.masked_before_purge = len(unmasked)
    if report.dry_run:
        return
    mask_names = tenant.get_settings().mask_person_names
    by_conversation: dict[uuid.UUID, list[Message]] = {}
    for message in unmasked:
        by_conversation.setdefault(message.conversation_id, []).append(message)
    for conversation_id, messages in by_conversation.items():
        conversation = db.get(Conversation, conversation_id)
        if conversation is not None:
            mask_messages(db, conversation, messages, mask_names=mask_names)
    db.flush()

    for chunk in _chunks([row.id for row in rows]):
        db.execute(
            update(Message)
            .where(Message.tenant_id == tenant.id, Message.id.in_(chunk))
            .values(text_raw=None, media_name=None),
            execution_options={"synchronize_session": False},
        )
    for chunk in _chunks(sorted({row.conversation_id for row in rows})):
        db.execute(
            update(Conversation)
            .where(Conversation.tenant_id == tenant.id, Conversation.id.in_(chunk))
            .values(raw_purged_at=now),
            execution_options={"synchronize_session": False},
        )


def _purge_media(
    db: Session,
    tenant: Tenant,
    cutoff: datetime,
    now: datetime,
    settings: Settings,
    report: RetentionReport,
) -> None:
    rows = db.execute(
        select(Message.id, Message.conversation_id, Message.media_path).where(
            Message.tenant_id == tenant.id,
            Message.created_at < cutoff,
            Message.media_path.is_not(None),
        )
    ).all()
    report.media_files_deleted = len(rows)
    if report.dry_run or not rows:
        return
    for row in rows:
        try:
            data_path(row.media_path, settings).unlink(missing_ok=True)
        except (OSError, ValueError):
            log.warning("audio_nao_removido", message_id=str(row.id))
    for chunk in _chunks([row.id for row in rows]):
        db.execute(
            update(Message)
            .where(Message.tenant_id == tenant.id, Message.id.in_(chunk))
            .values(media_path=None),
            execution_options={"synchronize_session": False},
        )
    for chunk in _chunks(sorted({row.conversation_id for row in rows})):
        db.execute(
            update(Conversation)
            .where(Conversation.tenant_id == tenant.id, Conversation.id.in_(chunk))
            .values(media_purged_at=now),
            execution_options={"synchronize_session": False},
        )


def _delete_stale_conversations(
    db: Session, tenant: Tenant, cutoff: datetime, settings: Settings, report: RetentionReport
) -> None:
    has_recent = exists().where(
        Message.conversation_id == Conversation.id, Message.created_at >= cutoff
    )
    stale = db.scalars(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id,
            Conversation.created_at < cutoff,
            ~has_recent,
        )
    ).all()
    report.conversations_deleted = len(stale)
    if report.dry_run:
        return
    for conversation in stale:
        delete_conversation(db, conversation, settings)


def run_retention(
    db: Session,
    tenant: Tenant,
    settings: Settings,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> RetentionReport:
    """Aplica a política da empresa. Quem chama faz o commit (e registra a auditoria)."""
    now = now or datetime.now(UTC)
    policy = tenant.get_settings()
    report = RetentionReport(tenant_id=tenant.id, dry_run=dry_run)
    if policy.retention_raw_days > 0:
        _purge_raw(db, tenant, now - timedelta(days=policy.retention_raw_days), now, report)
    if policy.retention_media_days > 0:
        cutoff = now - timedelta(days=policy.retention_media_days)
        _purge_media(db, tenant, cutoff, now, settings, report)
    if policy.retention_conversation_days > 0:
        cutoff = now - timedelta(days=policy.retention_conversation_days)
        _delete_stale_conversations(db, tenant, cutoff, settings, report)
    db.flush()
    db.expire_all()
    return report


def run_retention_all(
    settings: Settings, *, now: datetime | None = None, dry_run: bool = False
) -> list[RetentionReport]:
    """Roda a retenção de todas as empresas ativas, cada uma na própria transação."""
    with session_scope() as db:
        tenant_ids = list(db.scalars(select(Tenant.id).where(Tenant.is_active.is_(True))))
    reports = []
    for tenant_id in tenant_ids:
        try:
            with session_scope(tenant_id) as db:
                tenant = db.get(Tenant, tenant_id)
                if tenant is None:
                    continue
                report = run_retention(db, tenant, settings, now=now, dry_run=dry_run)
                if report.changed and not dry_run:
                    record_audit(
                        db,
                        tenant_id=tenant_id,
                        action=AuditAction.RETENTION_RUN,
                        actor_label="sistema (retenção agendada)",
                        details=report.as_dict(),
                    )
                reports.append(report)
        except Exception:
            log.exception("retencao_falhou", tenant_id=str(tenant_id))
            continue
        if report.changed:
            log.info("retencao_aplicada", **report.as_dict())
    return reports
