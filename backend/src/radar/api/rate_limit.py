"""Limite de taxa por janela fixa, em memória ou no Valkey/Redis."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

from fastapi import Request

from radar.api.errors import RateLimited
from radar.config import get_settings
from radar.logs import get_logger

log = get_logger(__name__)


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Registra um acesso. Devolve ``(permitido, segundos_ate_liberar)``."""
        ...


class MemoryRateLimiter:
    """Contador por janela fixa, por processo. Bom para dev, testes e instalação de um nó só."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}
        self.clock = clock

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = self.clock()
        window = int(now // window_seconds)
        with self._lock:
            current_window, count = self._windows.get(key, (window, 0))
            if current_window != window:
                current_window, count = window, 0
            count += 1
            self._windows[key] = (current_window, count)
            if len(self._windows) > 50_000:
                self._evict(window)
        retry_after = int((window + 1) * window_seconds - now) + 1
        return count <= limit, retry_after

    def _evict(self, current_window: int) -> None:
        stale = [key for key, (window, _) in self._windows.items() if window < current_window]
        for key in stale:
            del self._windows[key]

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


class RedisRateLimiter:
    """Mesma janela fixa, compartilhada entre processos da API."""

    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)
        self._fallback = MemoryRateLimiter()

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.time()
        window = int(now // window_seconds)
        redis_key = f"radar:rl:{key}:{window}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds + 5)
            count = int(pipe.execute()[0])
        except Exception as exc:
            # Falha no Valkey não pode derrubar a API: cai para o contador local.
            log.warning("rate_limit_redis_indisponivel", error=str(exc))
            return self._fallback.hit(key, limit, window_seconds)
        retry_after = int((window + 1) * window_seconds - now) + 1
        return count <= limit, retry_after


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.queue_mode == "rq":
        return RedisRateLimiter(settings.redis_url)
    return MemoryRateLimiter()


def reset_rate_limiter() -> None:
    get_rate_limiter.cache_clear()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def enforce(key: str, limit: int, *, window_seconds: int = 60) -> None:
    """Levanta :class:`RateLimited` se ``key`` passou do limite na janela."""
    if limit <= 0:
        return
    allowed, retry_after = get_rate_limiter().hit(_digest(key), limit, window_seconds)
    if not allowed:
        raise RateLimited(
            "Muitas requisições. Tente novamente em instantes.",
            headers={"Retry-After": str(retry_after)},
            details={"retry_after_seconds": retry_after},
        )
