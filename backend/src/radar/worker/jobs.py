"""Jobs executados pelo worker.

Cada job é uma função de módulo (o RQ a encontra pelo caminho), recebe só ids em texto e abre a
própria sessão de banco com o escopo da empresa.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from radar.logs import get_logger
from radar.worker.queue import enqueue
from radar.worker.runner import periodic

log = get_logger(__name__)

#: Transcrição + análise de uma conversa longa pode levar vários minutos em CPU.
CONVERSATION_TIMEOUT = 60 * 60


def process_import_job(import_id: str, tenant_id: str) -> None:
    from radar.services.ingestion import process_import

    process_import(uuid.UUID(import_id), uuid.UUID(tenant_id))


def process_conversation_job(conversation_id: str, tenant_id: str) -> None:
    from radar.services.processing import process_conversation

    process_conversation(uuid.UUID(conversation_id), uuid.UUID(tenant_id))


def prepare_conversation_job(conversation_id: str, tenant_id: str) -> None:
    from radar.services.processing import prepare_conversation

    prepare_conversation(uuid.UUID(conversation_id), uuid.UUID(tenant_id))


def enqueue_prepare(conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Transcreve e mascara logo (alguns segundos depois, para juntar uma rajada de mensagens)."""
    enqueue(
        prepare_conversation_job,
        str(conversation_id),
        str(tenant_id),
        job_id=f"preparar-{conversation_id}",
        delay=timedelta(seconds=5),
        job_timeout=CONVERSATION_TIMEOUT,
    )


def enqueue_import(import_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    enqueue(process_import_job, str(import_id), str(tenant_id), job_id=f"import-{import_id}")


def enqueue_conversation(conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    enqueue(
        process_conversation_job,
        str(conversation_id),
        str(tenant_id),
        job_id=f"conversa-{conversation_id}",
        job_timeout=CONVERSATION_TIMEOUT,
    )


@periodic("heartbeat", every=timedelta(minutes=5))
def heartbeat() -> None:
    """Prova de vida do conjunto agendador → fila → worker."""
    log.info("heartbeat")


@periodic("whatsapp_pausa", every=timedelta(minutes=5))
def analyze_idle_whatsapp() -> None:
    """Analisa as conversas do WhatsApp conectado que deram uma pausa."""
    from radar.config import get_settings
    from radar.integrations.whatsapp import enqueue_idle_conversations

    enqueue_idle_conversations(get_settings())


@periodic("retencao", every=timedelta(hours=6))
def retention() -> None:
    """Aplica a política de retenção de todas as empresas (LGPD)."""
    from radar.config import get_settings
    from radar.services.retention import run_retention_all

    run_retention_all(get_settings())
