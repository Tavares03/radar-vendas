"""Pipeline de processamento de uma conversa.

As etapas rodam em ordem e cada uma é opcional na prática: se falhar ou estiver desligada, as
seguintes continuam com o que houver (degradação graciosa). A lista cresce a cada fase do
projeto: transcrição → privacidade → análise → busca.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.config import Settings, get_settings
from radar.db.models import Conversation, Message, StageMetric
from radar.db.session import session_scope
from radar.logs import get_logger
from radar.observability import PIPELINE_STAGE_DURATION
from radar.services.analysis import analysis_stage
from radar.services.ingestion import data_path
from radar.services.privacy import privacy_stage
from radar.taxonomy import ConversationStatus, TranscriptionStatus
from radar.transcription import AudioTooLong, TranscriptionError, get_transcriber

log = get_logger(__name__)

#: Uma etapa pode devolver extras para a métrica (``provider``, ``tokens_in``, ``tokens_out``).
Stage = Callable[[Session, Conversation, Settings], dict[str, Any] | None]


def transcribe_stage(db: Session, conversation: Conversation, settings: Settings) -> None:
    """Transcreve os áudios pendentes. Cada áudio é independente: um erro não derruba os outros."""
    pending = db.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.transcription_status == TranscriptionStatus.PENDENTE,
        )
        .order_by(Message.sent_at, Message.position)
    ).all()
    if not pending:
        return
    transcriber = get_transcriber()
    for message in pending:
        if transcriber is None or not message.media_path:
            message.transcription_status = TranscriptionStatus.IGNORADA
            continue
        try:
            transcript = transcriber.transcribe(data_path(message.media_path, settings))
        except AudioTooLong as exc:
            message.transcription_status = TranscriptionStatus.IGNORADA
            log.info("audio_longo_ignorado", message_id=str(message.id), motivo=str(exc))
        except (TranscriptionError, OSError, ValueError) as exc:
            message.transcription_status = TranscriptionStatus.FALHOU
            log.warning("transcricao_falhou", message_id=str(message.id), error=str(exc))
        else:
            message.text_raw = transcript.text
            # O texto mudou: a máscara anterior (se havia) não vale mais.
            message.text_masked = None
            message.pii_spans = []
            message.media_seconds = transcript.duration_seconds
            message.transcription_model = transcript.model
            message.transcription_status = TranscriptionStatus.CONCLUIDA
        # Transcrever é lento: grava a cada áudio para não perder trabalho numa queda.
        db.commit()
    db.commit()


#: Etapas do pipeline, na ordem. Os módulos de cada fase acrescentam as suas com `register_stage`.
STAGES: list[tuple[str, Stage]] = [
    ("transcricao", transcribe_stage),
    ("privacidade", privacy_stage),
    ("analise", analysis_stage),
]


def register_stage(name: str, stage: Stage, *, before: str | None = None) -> None:
    """Acrescenta (ou substitui) uma etapa do pipeline."""
    for index, (existing, _) in enumerate(STAGES):
        if existing == name:
            STAGES[index] = (name, stage)
            return
    if before is not None:
        for index, (existing, _) in enumerate(STAGES):
            if existing == before:
                STAGES.insert(index, (name, stage))
                return
    STAGES.append((name, stage))


def prepare_conversation(conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Job leve: transcreve e mascara as mensagens novas, sem analisar nem mudar o status.

    Usado nas conversas ao vivo: o texto aparece mascarado no painel em segundos, e a análise
    (que gasta cota de LLM) espera a conversa dar uma pausa.
    """
    settings = get_settings()
    with session_scope(tenant_id) as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return
        for name, stage in (("transcricao", transcribe_stage), ("privacidade", privacy_stage)):
            try:
                stage(db, conversation, settings)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("preparo_falhou", etapa=name, conversation_id=str(conversation_id))


def process_conversation(conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Job: roda todas as etapas para uma conversa."""
    settings = get_settings()
    with session_scope(tenant_id) as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            log.warning("conversa_nao_encontrada", conversation_id=str(conversation_id))
            return
        conversation.status = ConversationStatus.PROCESSANDO
        conversation.status_detail = ""
        db.commit()

        failed: list[str] = []
        for name, stage in list(STAGES):
            started = time.perf_counter()
            outcome = "ok"
            extra: dict[str, Any] = {}
            try:
                extra = stage(db, conversation, settings) or {}
                db.commit()
            except Exception:
                db.rollback()
                outcome = "erro"
                failed.append(name)
                log.exception("etapa_falhou", etapa=name, conversation_id=str(conversation_id))
            finally:
                elapsed = time.perf_counter() - started
                PIPELINE_STAGE_DURATION.labels(stage=name, status=outcome).observe(elapsed)
                db.add(
                    StageMetric(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        stage=name,
                        status=outcome,
                        duration_ms=int(elapsed * 1000),
                        provider=str(extra.get("provider", ""))[:40],
                        tokens_in=int(extra.get("tokens_in", 0)),
                        tokens_out=int(extra.get("tokens_out", 0)),
                    )
                )
                db.commit()

        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return
        # Uma conversa ao vivo pode ter recebido mensagens durante a análise: ela volta a
        # "aguardando" para ser analisada de novo na próxima pausa, em vez de passar por pronta.
        db.refresh(conversation)
        if conversation.status is ConversationStatus.AGUARDANDO:
            conversation.updated_at = datetime.now(UTC)
            db.commit()
            return
        if failed:
            conversation.status = ConversationStatus.ERRO
            conversation.status_detail = "Etapas com erro: " + ", ".join(failed)
        else:
            conversation.status = ConversationStatus.ANALISADA
        conversation.updated_at = datetime.now(UTC)
        db.commit()
