"""Processos de longa duração: ``radar worker`` e ``radar scheduler``."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from datetime import timedelta
from types import FrameType

from radar.config import get_settings
from radar.logs import get_logger
from radar.runtime import init_storage
from radar.worker.queue import QUEUE_NAME, enqueue, get_queue, get_redis

log = get_logger(__name__)


def run_worker(*, burst: bool = False) -> None:
    """Consome a fila. Os jobs rodam neste mesmo processo para os modelos ficarem em memória."""
    settings = get_settings()
    init_storage(settings)

    if settings.queue_mode == "postgres":
        from radar.worker.pg_queue import PostgresWorker

        log.info("worker_iniciado", queue="postgres", burst=burst)
        handled = PostgresWorker().run(burst=burst)
        log.info("worker_encerrado", jobs=handled)
        return

    from rq import SimpleWorker

    worker = SimpleWorker([get_queue()], connection=get_redis())
    log.info("worker_iniciado", queue=QUEUE_NAME, burst=burst)
    worker.work(burst=burst, with_scheduler=True, logging_level=settings.log_level)


#: Tarefas periódicas: (nome, intervalo, função). Preenchida pelos módulos de jobs.
PERIODIC: list[tuple[str, timedelta, Callable[[], None]]] = []


def periodic(name: str, every: timedelta) -> Callable[[Callable[[], None]], Callable[[], None]]:
    """Registra uma função sem argumentos para rodar a cada ``every``."""

    def decorator(func: Callable[[], None]) -> Callable[[], None]:
        PERIODIC.append((name, every, func))
        return func

    return decorator


def run_scheduler(*, tick_seconds: float = 30.0, max_ticks: int | None = None) -> None:
    """Enfileira as tarefas periódicas no intervalo de cada uma.

    O ``job_id`` fixo impede acúmulo: se a execução anterior ainda está na fila, não entra outra.
    """
    import radar.worker.jobs  # noqa: F401  (registra as tarefas periódicas)

    stop = threading.Event()

    def _stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)

    elapsed = 0.0
    last_run: dict[str, float] = {}
    ticks = 0
    log.info("agendador_iniciado", tarefas=[name for name, _, _ in PERIODIC])
    while not stop.is_set():
        for name, every, func in PERIODIC:
            previous = last_run.get(name)
            if previous is None or elapsed - previous >= every.total_seconds():
                last_run[name] = elapsed
                try:
                    enqueue(func, job_id=f"periodic-{name}")
                    log.debug("tarefa_periodica_enfileirada", tarefa=name)
                except Exception:
                    log.exception("falha_ao_enfileirar", tarefa=name)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        stop.wait(tick_seconds)
        elapsed += tick_seconds
    log.info("agendador_encerrado")
