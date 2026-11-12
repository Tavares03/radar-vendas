"""Fila de jobs com três modos (``RADAR_QUEUE_MODE``).

- ``rq``: produção. Jobs vão para o Valkey/Redis e rodam no processo ``radar worker``.
- ``inline``: modo leve, sem Valkey. Jobs rodam numa thread do próprio processo da API.
- ``sync``: testes. O job roda na hora, na mesma thread, e os erros sobem para quem chamou.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from radar.config import get_settings
from radar.logs import get_logger
from radar.observability import JOBS

if TYPE_CHECKING:
    from redis import Redis
    from rq import Queue

log = get_logger(__name__)

QUEUE_NAME = "radar"
DEFAULT_JOB_TIMEOUT = 30 * 60
DEFAULT_RESULT_TTL = 3600
DEFAULT_FAILURE_TTL = 7 * 24 * 3600

_inline_executor: ThreadPoolExecutor | None = None
_inline_lock = threading.Lock()
_delayed_timers: list[threading.Timer] = []


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    from redis import Redis

    return Redis.from_url(get_settings().redis_url)


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    from rq import Queue

    return Queue(QUEUE_NAME, connection=get_redis(), default_timeout=DEFAULT_JOB_TIMEOUT)


def reset_queue_cache() -> None:
    get_redis.cache_clear()
    get_queue.cache_clear()


def _executor() -> ThreadPoolExecutor:
    global _inline_executor
    with _inline_lock:
        if _inline_executor is None:
            # Um job por vez: modelos de ML não são carregados em paralelo no modo leve.
            _inline_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-job")
        return _inline_executor


def _run_logged(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    name = getattr(func, "__name__", str(func))
    try:
        func(*args, **kwargs)
        JOBS.labels(job=name, status="ok").inc()
    except Exception:
        JOBS.labels(job=name, status="erro").inc()
        log.exception("job_falhou", job=name)


def enqueue(
    func: Callable[..., Any],
    *args: Any,
    job_id: str | None = None,
    delay: timedelta | None = None,
    job_timeout: int = DEFAULT_JOB_TIMEOUT,
    max_retries: int = 0,
    **kwargs: Any,
) -> str | None:
    """Agenda ``func(*args, **kwargs)``. Devolve o id do job no modo ``rq``.

    Com ``job_id``, um job igual que ainda esteja na fila não é duplicado.
    """
    mode = get_settings().queue_mode

    if mode == "sync":
        func(*args, **kwargs)
        return None

    if mode == "inline":
        if delay is not None and delay.total_seconds() > 0:
            timer = threading.Timer(
                delay.total_seconds(), lambda: _executor().submit(_run_logged, func, args, kwargs)
            )
            timer.daemon = True
            timer.start()
            _delayed_timers.append(timer)
        else:
            _executor().submit(_run_logged, func, args, kwargs)
        return None

    from rq import Retry
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    queue = get_queue()
    if job_id is not None:
        try:
            existing = Job.fetch(job_id, connection=get_redis())
            if existing.get_status(refresh=True) in ("queued", "scheduled", "deferred", "started"):
                return existing.id
        except NoSuchJobError:
            pass

    options: dict[str, Any] = {
        "job_timeout": job_timeout,
        "result_ttl": DEFAULT_RESULT_TTL,
        "failure_ttl": DEFAULT_FAILURE_TTL,
    }
    if job_id is not None:
        options["job_id"] = job_id
    if max_retries > 0:
        options["retry"] = Retry(max=max_retries, interval=[30, 120, 600][:max_retries] or 60)

    if delay is not None and delay.total_seconds() > 0:
        job = queue.enqueue_in(delay, func, *args, **options, **kwargs)
    else:
        job = queue.enqueue(func, *args, **options, **kwargs)
    return str(job.id)


def wait_inline_jobs(timeout: float = 60.0) -> None:
    """Espera a fila do modo ``inline`` esvaziar (útil em scripts e demos)."""
    done = threading.Event()
    _executor().submit(done.set)
    done.wait(timeout)
