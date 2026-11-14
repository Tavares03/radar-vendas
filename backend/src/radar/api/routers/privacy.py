"""Privacidade: direitos do titular e política de retenção (LGPD)."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from radar.api.deps import DbDep, SettingsDep, request_meta, require
from radar.api.errors import NotFound
from radar.api.schemas.privacy import (
    RetentionPolicyOut,
    RetentionReportOut,
    RetentionStatusOut,
    SubjectConversationOut,
    SubjectDeleteIn,
    SubjectDeletionOut,
    SubjectQuery,
    SubjectSearchOut,
)
from radar.auth.principal import Permission, Principal
from radar.db.models import Conversation, Tenant
from radar.services.audit import AuditAction, record_audit
from radar.services.retention import RetentionReport, run_retention
from radar.services.subjects import delete_subject, export_subject, find_subject

router = APIRouter(prefix="/privacy", tags=["privacidade"])

ManagerDep = Annotated[Principal, Depends(require(Permission.PRIVACY_MANAGE))]


def _tenant(db: DbDep, principal: Principal) -> Tenant:
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Empresa não encontrada.")
    return tenant


def _report_out(report: RetentionReport) -> RetentionReportOut:
    return RetentionReportOut(
        dry_run=report.dry_run,
        raw_messages_purged=report.raw_messages_purged,
        masked_before_purge=report.masked_before_purge,
        media_files_deleted=report.media_files_deleted,
        conversations_deleted=report.conversations_deleted,
    )


@router.post(
    "/subjects/search", response_model=SubjectSearchOut, summary="Localizar dados de um titular"
)
def search_subject(
    body: SubjectQuery, request: Request, db: DbDep, principal: ManagerDep
) -> SubjectSearchOut:
    """Conversas em que o titular participa ou é mencionado. Fica registrado na auditoria."""
    matches = find_subject(db, principal.tenant_id, body.identifiers)
    items = []
    for match in matches.values():
        conversation = db.get(Conversation, match.conversation_id)
        if conversation is None:
            continue
        items.append(
            SubjectConversationOut(
                conversation_id=conversation.id,
                relation=match.relation,
                mentions=len(match.mentions),
                customer_label=conversation.customer_label,
                seller_name=conversation.seller.display_name if conversation.seller else None,
                message_count=conversation.message_count,
                last_message_at=conversation.last_message_at,
            )
        )
    items.sort(key=lambda item: (item.relation != "participante", str(item.conversation_id)))
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.SUBJECT_SEARCHED,
        principal=principal,
        resource_type="subject",
        details={"identificadores": len(body.identifiers), "conversas": len(items)},
        **request_meta(request),
    )
    db.commit()
    return SubjectSearchOut(conversations=items)


@router.post(
    "/subjects/export",
    summary="Exportar os dados de um titular",
    response_class=Response,
    responses={200: {"content": {"application/json": {}}}},
)
def export_subject_data(
    body: SubjectQuery, request: Request, db: DbDep, principal: ManagerDep
) -> Response:
    """Relatório JSON para atender o direito de acesso (LGPD, art. 18, II)."""
    tenant = _tenant(db, principal)
    matches = find_subject(db, principal.tenant_id, body.identifiers)
    report = export_subject(db, tenant, matches)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.SUBJECT_EXPORTED,
        principal=principal,
        resource_type="subject",
        details={"identificadores": len(body.identifiers), "conversas": len(report["conversas"])},
        **request_meta(request),
    )
    db.commit()
    return Response(
        content=json.dumps(report, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="dados-do-titular.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/subjects/delete", response_model=SubjectDeletionOut, summary="Excluir os dados de um titular"
)
def delete_subject_data(
    body: SubjectDeleteIn,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: ManagerDep,
) -> SubjectDeletionOut:
    """Exclui as conversas em que o titular participa e apaga o texto original das mensagens de
    outras conversas que trazem dado dele (o texto mascarado fica). Não há como desfazer.

    Avalie antes as hipóteses de conservação do art. 16 da LGPD (obrigação legal, defesa em
    processo…): elas podem exigir manter parte dos dados.
    """
    tenant = _tenant(db, principal)
    matches = find_subject(db, principal.tenant_id, body.identifiers)
    result = delete_subject(db, tenant, body.identifiers, matches, settings)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.SUBJECT_DELETED,
        principal=principal,
        resource_type="subject",
        details={
            "identificadores": len(body.identifiers),
            "conversas_excluidas": result.conversations_deleted,
            "mensagens_anonimizadas": result.messages_redacted,
        },
        **request_meta(request),
    )
    db.commit()
    return SubjectDeletionOut(
        conversations_deleted=result.conversations_deleted,
        messages_redacted=result.messages_redacted,
    )


@router.get("/retention", response_model=RetentionStatusOut, summary="Política de retenção")
def retention_status(db: DbDep, settings: SettingsDep, principal: ManagerDep) -> RetentionStatusOut:
    """A política atual e o que seria apagado se a retenção rodasse agora."""
    tenant = _tenant(db, principal)
    policy = tenant.get_settings()
    report = run_retention(db, tenant, settings, dry_run=True)
    db.rollback()
    return RetentionStatusOut(
        policy=RetentionPolicyOut(
            retention_raw_days=policy.retention_raw_days,
            retention_media_days=policy.retention_media_days,
            retention_conversation_days=policy.retention_conversation_days,
        ),
        pending=_report_out(report),
    )


@router.post(
    "/retention/run", response_model=RetentionReportOut, summary="Aplicar a retenção agora"
)
def retention_run(
    request: Request, db: DbDep, settings: SettingsDep, principal: ManagerDep
) -> RetentionReportOut:
    """Aplica a política de retenção da empresa imediatamente (o agendador também a aplica)."""
    tenant = _tenant(db, principal)
    report = run_retention(db, tenant, settings)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.RETENTION_RUN,
        principal=principal,
        details=report.as_dict(),
        **request_meta(request),
    )
    db.commit()
    return _report_out(report)
