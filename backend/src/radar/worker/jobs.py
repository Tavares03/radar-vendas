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
