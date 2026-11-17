"""Limite de taxa (requisições e tokens por minuto) e circuit breaker por provedor.

Os limites dos planos gratuitos são baixos (a Groq libera poucos milhares de tokens por minuto em
alguns modelos). Respeitá-los aqui evita tomar 429 em sequência e esgotar a cota do dia.
O estado é por processo: cada worker controla o próprio ritmo.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

Clock = Callable[[], float]


class RateLimiter:
    """Janela deslizante de 60 s para requisições e tokens."""

    def __init__(
        self, requests_per_minute: int, tokens_per_minute: int, *, clock: Clock = time.monotonic
    ) -> None:
        self.rpm = max(1, requests_per_minute)
        self.tpm = max(1, tokens_per_minute)
        self._clock = clock
        self._events: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= 60:
            self._events.popleft()

    def wait_time(self, tokens: int) -> float:
        """Segundos até caber mais uma requisição de ``tokens`` (0 se já cabe)."""
        with self._lock:
            now = self._clock()
            self._trim(now)
            used_tokens = sum(t for _, t in self._events)
            if len(self._events) < self.rpm and used_tokens + tokens <= self.tpm:
                return 0.0
            if not self._events:
                return 0.0  # uma requisição maior que o limite inteiro: deixa passar sozinha
            return max(0.0, 60 - (now - self._events[0][0]))

    def consume(self, tokens: int) -> None:
        with self._lock:
            self._events.append((self._clock(), tokens))


class CircuitBreaker:
    """Depois de ``threshold`` falhas seguidas, para de usar o provedor por um tempo crescente."""

    def __init__(
        self,
        *,
        threshold: int = 3,
        cooldown_seconds: float = 60.0,
        max_cooldown_seconds: float = 600.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self.max_cooldown = max_cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._open_until = 0.0
        self._trips = 0

    def allow(self) -> bool:
        return self._clock() >= self._open_until

    def pause(self, seconds: float) -> None:
        """Deixa o provedor de lado por ``seconds`` sem contar falha (ex.: 429 com Retry-After)."""
        self._open_until = max(self._open_until, self._clock() + seconds)

    def record_success(self) -> None:
        self._failures = 0
        self._trips = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            delay = min(self.max_cooldown, self.cooldown * (2**self._trips))
            self._open_until = self._clock() + delay
            self._trips += 1
            self._failures = 0
