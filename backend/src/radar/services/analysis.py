"""Etapa de análise do pipeline: monta a entrada (só texto mascarado), roda as camadas e grava a
análise e os alertas.

Reanalisar não apaga o trabalho humano: um alerta é reconhecido pela impressão digital (tipo +
mensagem), então status, responsável e nota de revisão continuam. Alertas abertos que não se
repetem na nova análise somem; os revisados ficam como registro.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import cache
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from radar.analysis import (
    ConversationAnalysis,
    ConversationInput,
    MessageInput,
    analyze_conversation,
)
from radar.analysis.llm_analyzer import RouterAnalyzer
from radar.analysis.models import MessageClassifier
from radar.config import Settings
from radar.db.models import Alert, Analysis, Conversation, Message, Tenant, TenantPlaybook
from radar.llm import LLMRouter, build_router
from radar.logs import get_logger
from radar.playbooks import Playbook, PlaybookError, parse_playbook, read_builtin
from radar.services.ingestion import tenant_timezone
from radar.taxonomy import AlertStatus, ImportSource, SenderRole, Severity

log = get_logger(__name__)

#: Alertas que ainda pedem atenção (contam em ``open_alerts`` e na severidade da conversa).
OPEN_STATUSES = frozenset({AlertStatus.ABERTO, AlertStatus.EM_REVISAO, AlertStatus.CONFIRMADO})
_SEVERITY_RANK = {s.value: s.rank for s in Severity}

# ---------------------------------------------------------------- LLM e classificador
_router_override: LLMRouter | None = None
_has_override = False


def set_llm_router(router: LLMRouter | None, *, clear: bool = False) -> None:
    """Troca o roteador de LLM do processo (testes e demos). ``clear=True`` volta ao padrão."""
    global _router_override, _has_override
    _router_override, _has_override = (None, False) if clear else (router, True)
    _router_for.cache_clear()


@cache
def _router_for(mode: str) -> LLMRouter | None:
    return build_router(mode=mode)  # type: ignore[arg-type]


def llm_mode(tenant: Tenant, settings: Settings) -> str:
    chosen = tenant.get_settings().llm_mode
    return settings.llm_mode if chosen == "herdar" else chosen


def get_analyzer(mode: str, settings: Settings) -> RouterAnalyzer | None:
    if _has_override:
        router = _router_override
    elif mode == "off":
        return None
    else:
        router = _router_for(mode)
    if router is None:
        return None
    return RouterAnalyzer(router, max_conversation_tokens=settings.llm_max_conversation_tokens)


def get_classifier() -> MessageClassifier | None:
    """Classificador próprio (ONNX), se houver; sem ele a análise segue com regras e LLM."""
    from radar.ml.loader import load_classifier

    return load_classifier()


# ---------------------------------------------------------------- playbook
def playbook_resolver(db: Session) -> Any:
    def resolve(slug: str) -> str | None:
        row = db.scalar(
            select(TenantPlaybook).where(
                TenantPlaybook.slug == slug, TenantPlaybook.is_active.is_(True)
            )
        )
        return row.content if row is not None else read_builtin(slug)

    return resolve


def resolve_playbook(db: Session, slug: str) -> tuple[Playbook, int]:
    """Playbook da empresa (se houver) ou o padrão; ``generico`` se o nome não existir."""
    resolve = playbook_resolver(db)
    row = db.scalar(
        select(TenantPlaybook).where(
            TenantPlaybook.slug == slug, TenantPlaybook.is_active.is_(True)
        )
    )
    text = resolve(slug)
    if text is not None:
        try:
            return parse_playbook(text, resolver=resolve), row.version if row else 1
        except PlaybookError:
            log.exception("playbook_invalido", playbook=slug)
    return parse_playbook(read_builtin("generico") or "", resolver=resolve), 1


# ---------------------------------------------------------------- entrada
def build_input(
    db: Session, conversation: Conversation, tenant: Tenant, playbook: Playbook
) -> tuple[ConversationInput, list[Message]]:
    rows = [
        m
        for m in db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.sent_at, Message.position)
        )
        if m.sender_role in (SenderRole.VENDEDOR, SenderRole.CLIENTE)
    ]
    messages = [
        MessageInput(index, row.sender_role, row.text_masked or "", row.sent_at, row.kind, row.id)
        for index, row in enumerate(rows)
    ]
    now = datetime.now(UTC)
    if conversation.source is ImportSource.WHATSAPP_EXPORT and rows:
        # Um export é uma foto: o "agora" da conversa é quando ela chegou ao Radar.
        reference = max(row.created_at for row in rows)
    else:
        reference = now
    settings = tenant.get_settings()
    return (
        ConversationInput(
            messages=messages,
            playbook=playbook,
            timezone=tenant_timezone(tenant),
            business_hours=settings.business_hours,
            reference_time=reference,
            response_sla_minutes=settings.response_sla_minutes,
            follow_up_hours=settings.follow_up_hours,
            conversation_id=conversation.id,
        ),
        rows,
    )


# ---------------------------------------------------------------- gravação
def _fingerprint(alert_type: str, message: Message | None) -> str:
    anchor = message.dedupe_hash if message is not None else "conversa"
    return hashlib.sha256(f"{alert_type}|{anchor}".encode()).hexdigest()


def refresh_alert_summary(db: Session, conversation: Conversation) -> None:
    """Atualiza ``open_alerts`` e ``max_severity`` da conversa a partir dos alertas."""
    db.flush()
    open_alerts = db.scalars(
        select(Alert).where(
            Alert.conversation_id == conversation.id, Alert.status.in_(OPEN_STATUSES)
        )
    ).all()
    conversation.open_alerts = len(open_alerts)
    conversation.max_severity = max(
        (a.severity for a in open_alerts), key=lambda s: _SEVERITY_RANK.get(s, 0), default=None
    )


def save_analysis(
    db: Session,
    conversation: Conversation,
    result: ConversationAnalysis,
    rows: Sequence[Message],
    playbook: Playbook,
    playbook_version: int,
    duration_ms: int,
) -> Analysis:
    db.execute(
        update(Analysis)
        .where(Analysis.conversation_id == conversation.id, Analysis.is_current.is_(True))
        .values(is_current=False),
        execution_options={"synchronize_session": False},
    )
    analysis = Analysis(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        score=result.score,
        playbook=playbook.id,
        playbook_version=playbook_version,
        summary=result.summary,
        suggestion=result.suggestion,
        sentiment=result.sentiment,
        stage=result.stage,
        layers=result.layers,
        criteria=[
            {
                "id": c.id,
                "label": c.label,
                "points": c.points,
                "maximum": c.maximum,
                "justification": c.justification,
                "estimated": c.estimated,
            }
            for c in result.criteria
        ],
        details={
            "objections": [o.model_dump() for o in result.objections],
            "requests": [r.model_dump() for r in result.requests],
            "metrics": {
                "median_reply_minutes": result.metrics.median_reply_minutes,
                "max_reply_minutes": result.metrics.max_reply_minutes,
                "silence_hours": round(result.metrics.silence_hours, 1),
                "follow_up_missing": result.metrics.follow_up_missing,
            },
            "message_labels": {str(k): v for k, v in result.message_labels.items()},
            "discarded": result.discarded,
            "strengths": result.strengths,
            "improvements": result.improvements,
            "injection_suspected": result.injection_suspected,
        },
        llm_provider=str(result.llm.get("provider", ""))[:40],
        llm_model=str(result.llm.get("model", ""))[:120],
        llm_error=result.llm_error or "",
        tokens_in=int(result.llm.get("tokens_in", 0)),
        tokens_out=int(result.llm.get("tokens_out", 0)),
        duration_ms=duration_ms,
    )
    db.add(analysis)
    db.flush()

    existing = {
        alert.fingerprint: alert
        for alert in db.scalars(select(Alert).where(Alert.conversation_id == conversation.id))
    }
    seen: set[str] = set()
    for finding in result.findings:
        message = rows[finding.message_index] if finding.message_index is not None else None
        fingerprint = _fingerprint(finding.type, message)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        alert = existing.get(fingerprint)
        if alert is None:
            alert = Alert(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                fingerprint=fingerprint,
                status=AlertStatus.ABERTO,
            )
            db.add(alert)
        alert.analysis_id = analysis.id
        alert.message_id = message.id if message is not None else None
        alert.seller_id = conversation.seller_id
        alert.type = finding.type
        alert.category = finding.category
        alert.severity = finding.severity
        alert.message_index = finding.message_index
        alert.evidence = finding.evidence
        alert.explanation = finding.explanation
        alert.sources = finding.sources
        alert.confidence = finding.confidence
        alert.contested = finding.contested
    for fingerprint, alert in existing.items():
        if fingerprint not in seen and alert.status is AlertStatus.ABERTO:
            db.delete(alert)

    conversation.score = result.score
    conversation.analyzed_at = datetime.now(UTC)
    refresh_alert_summary(db, conversation)
    return analysis


def analysis_stage(
    db: Session, conversation: Conversation, settings: Settings
) -> dict[str, Any] | None:
    tenant = db.get(Tenant, conversation.tenant_id)
    if tenant is None:
        return None
    playbook, version = resolve_playbook(db, conversation.playbook)
    conversation_input, rows = build_input(db, conversation, tenant, playbook)
    if not conversation_input.messages:
        return None
    started = time.perf_counter()
    result = analyze_conversation(
        conversation_input,
        llm=get_analyzer(llm_mode(tenant, settings), settings),
        classifier=get_classifier(),
    )
    duration = int((time.perf_counter() - started) * 1000)
    save_analysis(db, conversation, result, rows, playbook, version, duration)
    if result.llm_error:
        log.warning(
            "analise_sem_llm", conversation_id=str(conversation.id), motivo=result.llm_error
        )
    return {
        "provider": result.llm.get("provider", ""),
        "tokens_in": result.llm.get("tokens_in", 0),
        "tokens_out": result.llm.get("tokens_out", 0),
    }


def current_analysis(db: Session, conversation_id: Any) -> Analysis | None:
    return db.scalar(
        select(Analysis)
        .where(Analysis.conversation_id == conversation_id, Analysis.is_current.is_(True))
        .order_by(Analysis.created_at.desc())
    )


def alert_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Alert.severity, func.count())
        .where(Alert.status.in_(OPEN_STATUSES))
        .group_by(Alert.severity)
    )
    return dict(rows)
