"""Fila de jobs guardada no próprio PostgreSQL (``RADAR_QUEUE_MODE=postgres``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from radar.db.base import Base, utcnow
from radar.db.types import JSONType, UtcDateTime


class QueuedJob(Base):
    """Um job da fila: a função (pelo caminho ``modulo:nome``), os argumentos e o estado.

    Não pertence a uma empresa: os jobs recebem o ``tenant_id`` como argumento e abrem a própria
    sessão com o escopo dela (ver :mod:`radar.worker.jobs`).
    """

    __tablename__ = "job_queue"
    __table_args__ = (Index("ix_job_queue_pending", "status", "run_at"),)

    #: O ``job_id`` de quem enfileirou (``import-…``, ``conversa-…``) ou um id sorteado.
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    func: Mapped[str] = mapped_column(String(200), nullable=False)
    args: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    kwargs: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    #: ``queued``, ``started``, ``finished`` ou ``failed``.
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Quando o job pode rodar (atraso e espera entre tentativas).
    run_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enqueued_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Traceback da última falha (vazio quando deu certo).
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
