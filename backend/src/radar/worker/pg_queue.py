"""Fila de jobs no PostgreSQL (``RADAR_QUEUE_MODE=postgres``): o banco é a única dependência.

Os jobs ficam na tabela ``job_queue``. O ``radar worker`` pega o próximo com
``SELECT … FOR UPDATE SKIP LOCKED``, então vários workers podem rodar juntos sem pegar o mesmo job.
Mantém o que o projeto usava do RQ:

- **deduplicação**: com ``job_id``, um job igual ainda na fila (ou rodando) não é duplicado;
- **atraso** e **retentativas** com espera crescente (30 s, 2 min, 10 min);
- **timeout** por job (``SIGALRM`` no processo do worker, como o ``SimpleWorker`` do RQ);
- **jobs abandonados** (worker morto no meio) voltam para a fila depois do timeout;
- **limpeza**: concluídos somem depois de 1 h e falhos depois de 7 dias.

Ao receber SIGTERM no meio de um job (``docker compose stop``), o worker interrompe o job e o
devolve para a fila sem contar tentativa; o próximo worker recomeça do zero. Os jobs do Radar são
idempotentes (reprocessar uma importação ou conversa não duplica nada).
"""

from __future__ import annotations

import importlib
import signal
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import FrameType
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from radar.db.base import utcnow
from radar.db.models import QueuedJob
from radar.db.session import session_scope
from radar.logs import get_logger
from radar.observability import JOBS

log = get_logger(__name__)

QUEUED = "queued"
STARTED = "started"
FINISHED = "finished"
FAILED = "failed"
#: Estados em que um novo ``enqueue`` com o mesmo ``job_id`` é ignorado.
ACTIVE = (QUEUED, STARTED)

RETRY_INTERVALS = (30, 120, 600)
#: Folga além do timeout antes de considerar um job ``started`` abandonado.
STALE_GRACE = timedelta(minutes=1)
FINISHED_TTL = timedelta(hours=1)
FAILED_TTL = timedelta(days=7)
POLL_SECONDS = 2.0
HOUSEKEEPING_SECONDS = 300.0
MAX_ERROR_CHARS = 8000


class JobTimeoutError(BaseException):
    """O job passou do tempo limite.

    Herda de ``BaseException`` para que um ``except Exception`` dentro do job não o engula.
    """


class WorkerShutdownError(BaseException):
    """O worker recebeu SIGTERM/SIGINT no meio de um job."""


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    func: str
    args: list[Any]
    kwargs: dict[str, Any]
    attempts: int
    max_retries: int
    timeout_seconds: int
    #: Identifica esta reserva: se o job for recuperado e pego de novo, o valor muda.
    started_at: datetime

    @property
    def name(self) -> str:
        return self.func.rpartition(":")[2]


# ------------------------------------------------------------------------------- funções
def func_path(func: Callable[..., Any]) -> str:
    """``modulo:nome`` de uma função de módulo (o worker a importa por esse caminho)."""
    path = f"{func.__module__}:{func.__qualname__}"
    if "<" in path:
        raise ValueError(
            f"{path}: só funções definidas no nível do módulo podem ir para a fila "
            "(nada de lambda ou função aninhada)"
        )
    return path


def resolve(path: str) -> Callable[..., Any]:
    module_name, _, qualname = path.partition(":")
    target: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise TypeError(f"{path} não é uma função")
    return target  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------- enfileirar
def _upsert(db: Session) -> Any:
    return pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert


def enqueue(
    func: Callable[..., Any],
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    *,
    job_id: str | None = None,
    delay: timedelta | None = None,
    job_timeout: int,
    max_retries: int = 0,
) -> str:
    """Grava o job na fila e devolve o id. Um job ativo com o mesmo ``job_id`` fica como está."""
    path = func_path(func)
    job_id = job_id or uuid.uuid4().hex
    now = utcnow()
    run_at = now + delay if delay is not None and delay.total_seconds() > 0 else now
    values: dict[str, Any] = {
        "id": job_id,
        "func": path,
        "args": list(args),
        "kwargs": dict(kwargs or {}),
        "status": QUEUED,
        "run_at": run_at,
        "attempts": 0,
        "max_retries": max_retries,
        "timeout_seconds": job_timeout,
        "enqueued_at": now,
        "started_at": None,
        "finished_at": None,
        "error": "",
    }
    with session_scope() as db:
        statement = _upsert(db)(QueuedJob).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[QueuedJob.id],
            set_={key: statement.excluded[key] for key in values if key != "id"},
            # Ainda na fila ou rodando: não duplica. Concluído ou falho: volta para a fila.
            where=QueuedJob.status.not_in(ACTIVE),
        )
        db.execute(statement)
    return job_id


# ------------------------------------------------------------------------------- consumir
def claim_next(now: datetime | None = None) -> ClaimedJob | None:
    """Marca como ``started`` o próximo job pronto para rodar e o devolve (``None`` se não há)."""
    now = now or utcnow()
    with session_scope() as db:
        job = db.scalars(
            select(QueuedJob)
            .where(QueuedJob.status == QUEUED, QueuedJob.run_at <= now)
            .order_by(QueuedJob.run_at, QueuedJob.enqueued_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            return None
        job.status = STARTED
        job.started_at = now
        job.attempts += 1
        return ClaimedJob(
            id=job.id,
            func=job.func,
            args=list(job.args),
            kwargs=dict(job.kwargs),
            attempts=job.attempts,
            max_retries=job.max_retries,
            timeout_seconds=job.timeout_seconds,
            started_at=now,
        )


def _retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=RETRY_INTERVALS[min(attempts, len(RETRY_INTERVALS)) - 1])


def _record_result(job: ClaimedJob, error: str | None) -> None:
    with session_scope() as db:
        row = db.get(QueuedJob, job.id, with_for_update=True)
        if row is None or row.status != STARTED or row.started_at != job.started_at:
            return  # apagado ou recuperado por outro worker enquanto rodava
        now = utcnow()
        if error is None:
            row.status, row.finished_at, row.error = FINISHED, now, ""
        elif job.attempts <= job.max_retries:
            row.status, row.started_at, row.error = QUEUED, None, error
            row.run_at = now + _retry_delay(job.attempts)
        else:
            row.status, row.finished_at, row.error = FAILED, now, error


def release(job: ClaimedJob) -> None:
    """Devolve um job interrompido para a fila, sem contar a tentativa."""
    with session_scope() as db:
        db.execute(
            update(QueuedJob)
            .where(
                QueuedJob.id == job.id,
                QueuedJob.status == STARTED,
                QueuedJob.started_at == job.started_at,
            )
            .values(
                status=QUEUED,
                started_at=None,
                run_at=utcnow(),
                attempts=QueuedJob.attempts - 1,
            )
            .execution_options(synchronize_session=False)
        )


@contextmanager
def time_limit(seconds: int) -> Iterator[None]:
    """Interrompe o bloco com :class:`JobTimeoutError` depois de ``seconds`` (só na thread principal)."""
    if (
        seconds <= 0
        or not hasattr(signal, "SIGALRM")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def _expire(_signum: int, _frame: FrameType | None) -> None:
        raise JobTimeoutError(f"o job passou do limite de {seconds} s")

    previous = signal.signal(signal.SIGALRM, _expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def recover_abandoned(now: datetime | None = None) -> int:
    """Jobs ``started`` há mais que o timeout: o worker que os pegou morreu (OOM, kill -9…).

    Voltam para a fila se ainda têm tentativas; senão viram ``failed``.
    """
    now = now or utcnow()
    recovered = 0
    with session_scope() as db:
        rows = db.scalars(
            select(QueuedJob).where(QueuedJob.status == STARTED).with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            started = row.started_at or row.enqueued_at
            if started + timedelta(seconds=row.timeout_seconds) + STALE_GRACE > now:
                continue
            recovered += 1
            row.error = "abandonado: o worker parou no meio do job"
            if row.attempts <= row.max_retries:
                row.status, row.started_at, row.run_at = QUEUED, None, now
            else:
                row.status, row.finished_at = FAILED, now
            log.warning("job_abandonado", job_id=row.id, status_novo=row.status)
    return recovered


def purge_old(now: datetime | None = None) -> int:
    """Apaga os concluídos com mais de 1 h e os falhos com mais de 7 dias."""
    now = now or utcnow()
    with session_scope() as db:
        finished = db.execute(
            delete(QueuedJob)
            .where(QueuedJob.status == FINISHED, QueuedJob.finished_at < now - FINISHED_TTL)
            .execution_options(synchronize_session=False)
        )
        failed = db.execute(
            delete(QueuedJob)
            .where(QueuedJob.status == FAILED, QueuedJob.finished_at < now - FAILED_TTL)
            .execution_options(synchronize_session=False)
        )
        return int(getattr(finished, "rowcount", 0) or 0) + int(getattr(failed, "rowcount", 0) or 0)


# ------------------------------------------------------------------------------- worker
class PostgresWorker:
    """Consome a fila neste processo, um job por vez, na thread principal.

    Os jobs rodam aqui mesmo (sem fork) para os modelos ONNX e o Whisper ficarem em memória.
    """

    def __init__(self, *, poll_seconds: float = POLL_SECONDS) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._in_job = False
        self._last_housekeeping = float("-inf")

    def stop(self) -> None:
        self._stop.set()

    def _on_signal(self, _signum: int, _frame: FrameType | None) -> None:
        self._stop.set()
        if self._in_job:
            raise WorkerShutdownError

    def housekeeping(self) -> None:
        try:
            recovered = recover_abandoned()
            purged = purge_old()
        except Exception:
            log.exception("fila_limpeza_falhou")
            return
        if recovered or purged:
            log.info("fila_limpeza", recuperados=recovered, apagados=purged)

    def execute(self, job: ClaimedJob) -> bool:
        """Roda um job já reservado e grava o resultado. Devolve ``True`` se deu certo."""
        error: str | None = None
        try:
            func = resolve(job.func)
            self._in_job = True
            try:
                with time_limit(job.timeout_seconds):
                    func(*job.args, **job.kwargs)
            finally:
                self._in_job = False
        except (Exception, JobTimeoutError):
            error = traceback.format_exc()[-MAX_ERROR_CHARS:]
            retry = job.attempts <= job.max_retries
            log.exception(
                "job_falhou",
                job=job.name,
                job_id=job.id,
                tentativa=job.attempts,
                vai_tentar_de_novo=retry,
            )
        JOBS.labels(job=job.name, status="ok" if error is None else "erro").inc()
        _record_result(job, error)
        return error is None

    def run(self, *, burst: bool = False) -> int:
        """Processa jobs até receber SIGTERM/SIGINT (ou, com ``burst``, até a fila esvaziar).

        Devolve quantos jobs rodou.
        """
        handled = 0
        previous: dict[signal.Signals, Any] = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, self._on_signal)
        try:
            while not self._stop.is_set():
                if time.monotonic() - self._last_housekeeping >= HOUSEKEEPING_SECONDS:
                    self._last_housekeeping = time.monotonic()
                    self.housekeeping()
                job = claim_next()
                if job is None:
                    if burst:
                        break
                    self._stop.wait(self.poll_seconds)
                    continue
                try:
                    self.execute(job)
                    handled += 1
                except WorkerShutdownError:
                    release(job)
                    log.warning("job_devolvido_para_a_fila", job=job.name, job_id=job.id)
                    break
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        return handled
