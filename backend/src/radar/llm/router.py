"""Roteador de LLMs: failover entre provedores, retry com backoff, limite de taxa, circuit
breaker, cache e saída estruturada validada com Pydantic (com reparo).

Privacidade: antes de mandar qualquer coisa a um provedor de nuvem, o roteador passa o prompt pela
trava :func:`radar.privacy.guard.ensure_masked`. Se ainda houver dado pessoal, só provedores
locais (Ollama) podem receber; sem eles, a chamada falha com :class:`LLMUnavailable`.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from radar.analysis.models import LLMUnavailable
from radar.llm.cache import FileCache
from radar.llm.limits import CircuitBreaker
from radar.llm.providers import ChatResult, Provider, ProviderError
from radar.logs import get_logger
from radar.privacy.guard import UnmaskedDataError, ensure_masked

log = get_logger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def repair_json(text: str) -> Any:
    """JSON da resposta, tolerando cerca de código, texto em volta e vírgula sobrando."""
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    for candidate in candidates:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            continue
        chunk = _TRAILING_COMMA_RE.sub(r"\1", candidate[start : end + 1])
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    raise ValueError("a resposta não tem um objeto JSON válido")


@dataclass(frozen=True, slots=True)
class StructuredResult[T: BaseModel]:
    value: T
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cached: bool = False


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class LLMRouter:
    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        cache: FileCache | None = None,
        max_retries: int = 2,
        backoff_seconds: float = 2.0,
        max_wait_seconds: float = 20.0,
        throttle_wait_seconds: float = 65.0,
        breaker_threshold: int = 3,
        max_tokens: int = 1800,
        temperature: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.providers = list(providers)
        self.cache = cache
        self.max_retries = max_retries
        self.backoff = backoff_seconds
        #: Espera aceitável num provedor antes de tentar o próximo da lista.
        self.max_wait = max_wait_seconds
        #: Com todos os provedores só no limite de taxa, quanto esperar pelo primeiro que liberar
        #: (a janela dos limites é de 60 s). A análise roda no worker, em segundo plano.
        self.throttle_wait = throttle_wait_seconds
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._sleep = sleep
        self._breakers = {
            p.name: CircuitBreaker(threshold=breaker_threshold) for p in self.providers
        }

    def _breaker(self, provider: Provider) -> CircuitBreaker:
        return self._breakers.setdefault(provider.name, CircuitBreaker())

    def _estimate(self, messages: Sequence[dict[str, str]]) -> int:
        return sum(_estimate_tokens(m["content"]) for m in messages) + self.max_tokens

    def _parse[T: BaseModel](self, text: str, schema: type[T]) -> T:
        return schema.model_validate(repair_json(text))

    def _chat(
        self, provider: Provider, messages: list[dict[str, str]], temperature: float
    ) -> ChatResult:
        estimate = self._estimate(messages)
        wait = provider.limiter.wait_time(estimate)
        if wait:
            self._sleep(wait)
        provider.limiter.consume(estimate)
        return provider.chat(messages, max_tokens=self.max_tokens, temperature=temperature)

    def _call[T: BaseModel](
        self, provider: Provider, messages: list[dict[str, str]], schema: type[T]
    ) -> tuple[T, ChatResult]:
        """Uma tentativa completa num provedor: chamada + validação + (se preciso) um reparo."""
        result = self._chat(provider, messages, self.temperature)
        try:
            return self._parse(result.text, schema), result
        except (ValueError, ValidationError) as exc:
            problem = str(exc)[:600]
        repair = [
            *messages,
            {"role": "assistant", "content": result.text[:4000]},
            {
                "role": "user",
                "content": (
                    "Sua resposta não seguiu o formato pedido. Problema: "
                    f"{problem}\nResponda de novo apenas com o JSON válido, com os campos e tipos "
                    "pedidos, sem texto antes ou depois."
                ),
            },
        ]
        fixed = self._chat(provider, repair, 0)
        tokens = ChatResult(
            text=fixed.text,
            provider=result.provider,
            model=result.model,
            tokens_in=result.tokens_in + fixed.tokens_in,
            tokens_out=result.tokens_out + fixed.tokens_out,
        )
        try:
            return self._parse(fixed.text, schema), tokens
        except (ValueError, ValidationError) as exc:
            raise ProviderError("JSON inválido mesmo após reparo", retryable=False) from exc

    def _attempt[T: BaseModel](
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        schema: type[T],
        cache_key: str,
        errors: list[str],
    ) -> StructuredResult[T] | None:
        """Tenta um provedor (com retries). ``None`` se não deu; o motivo vai para ``errors``."""
        breaker = self._breaker(provider)
        for attempt in range(self.max_retries + 1):
            try:
                value, result = self._call(provider, messages, schema)
            except ProviderError as exc:
                if exc.retry_after is not None and exc.retry_after > self.max_wait:
                    # O provedor pediu uma pausa longa (cota do minuto ou do dia): segue para o
                    # próximo e só volta a este depois do prazo, sem contar como falha.
                    breaker.pause(exc.retry_after)
                    errors.append(f"{provider.name}: {exc} (pausado por {exc.retry_after:.0f} s)")
                    log.warning(
                        "llm_provedor_pediu_pausa",
                        provedor=provider.name,
                        segundos=round(exc.retry_after),
                    )
                    return None
                if exc.retryable and attempt < self.max_retries:
                    delay = exc.retry_after
                    self._sleep(delay if delay is not None else self.backoff * (2**attempt))
                    continue
                errors.append(f"{provider.name}: {exc}")
                breaker.record_failure()
                log.warning("llm_provedor_falhou", provedor=provider.name, erro=str(exc))
                return None
            breaker.record_success()
            if self.cache is not None:
                self.cache.set(
                    cache_key,
                    {
                        "value": value.model_dump(mode="json"),
                        "provider": result.provider,
                        "model": result.model,
                    },
                )
            return StructuredResult(
                value=value,
                provider=result.provider,
                model=result.model,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
            )
        return None

    def complete_json[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> StructuredResult[T]:
        key = hashlib.sha256(
            "\x1f".join(
                [
                    system,
                    user,
                    schema.__name__,
                    json.dumps(schema.model_json_schema(), sort_keys=True),
                ]
            ).encode()
        ).hexdigest()
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                try:
                    return StructuredResult(
                        value=schema.model_validate(cached["value"]),
                        provider=str(cached.get("provider", "")),
                        model=str(cached.get("model", "")),
                        tokens_in=0,
                        tokens_out=0,
                        cached=True,
                    )
                except (KeyError, ValidationError):
                    pass

        try:
            ensure_masked(user)
            cloud_allowed = True
        except UnmaskedDataError:
            cloud_allowed = False
            log.warning("prompt_com_dado_pessoal_bloqueado_para_nuvem")

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        estimate = self._estimate(messages)
        errors: list[str] = []
        throttled: list[tuple[float, Provider]] = []
        for provider in self.providers:
            if not provider.local and not cloud_allowed:
                errors.append(f"{provider.name}: bloqueado (texto com dado pessoal)")
                continue
            if not self._breaker(provider).allow():
                errors.append(f"{provider.name}: pausado após falhas ou a pedido do provedor")
                continue
            wait = provider.limiter.wait_time(estimate)
            if wait > self.max_wait:
                # Limite do próprio Radar, não falha do provedor: não conta no circuit breaker.
                throttled.append((wait, provider))
                errors.append(f"{provider.name}: limite de taxa (espera de {wait:.0f} s)")
                continue
            outcome = self._attempt(provider, messages, schema, key, errors)
            if outcome is not None:
                return outcome

        if throttled:
            wait, provider = min(throttled, key=lambda item: item[0])
            if wait <= self.throttle_wait:
                log.info(
                    "llm_aguardando_limite_de_taxa", provedor=provider.name, segundos=round(wait)
                )
                self._sleep(wait)
                outcome = self._attempt(provider, messages, schema, key, errors)
                if outcome is not None:
                    return outcome
        raise LLMUnavailable(
            "Nenhum provedor de LLM respondeu: " + "; ".join(errors or ["nenhum configurado"])
        )
