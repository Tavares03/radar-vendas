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
        breaker_threshold: int = 3,
        max_tokens: int = 1800,
        temperature: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.providers = list(providers)
        self.cache = cache
        self.max_retries = max_retries
        self.backoff = backoff_seconds
        self.max_wait = max_wait_seconds
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._sleep = sleep
        self._breakers = {
            p.name: CircuitBreaker(threshold=breaker_threshold) for p in self.providers
        }

    def _parse[T: BaseModel](self, text: str, schema: type[T]) -> T:
        return schema.model_validate(repair_json(text))

    def _call[T: BaseModel](
        self, provider: Provider, messages: list[dict[str, str]], schema: type[T]
    ) -> tuple[T, ChatResult]:
        """Uma tentativa completa num provedor: chamada + validação + (se preciso) um reparo."""
        estimate = sum(_estimate_tokens(m["content"]) for m in messages) + self.max_tokens
        wait = provider.limiter.wait_time(estimate)
        if wait > self.max_wait:
            raise ProviderError(f"limite de taxa (espera de {wait:.0f} s)", retryable=False)
        if wait:
            self._sleep(wait)
        provider.limiter.consume(estimate)
        result = provider.chat(messages, max_tokens=self.max_tokens, temperature=self.temperature)
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
        fixed = provider.chat(repair, max_tokens=self.max_tokens, temperature=0)
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
        errors: list[str] = []
        for provider in self.providers:
            if not provider.local and not cloud_allowed:
                errors.append(f"{provider.name}: bloqueado (texto com dado pessoal)")
                continue
            breaker = self._breakers.setdefault(provider.name, CircuitBreaker())
            if not breaker.allow():
                errors.append(f"{provider.name}: pausado após falhas seguidas")
                continue
            for attempt in range(self.max_retries + 1):
                try:
                    value, result = self._call(provider, messages, schema)
                except ProviderError as exc:
                    if exc.retryable and attempt < self.max_retries:
                        self._sleep(self.backoff * (2**attempt))
                        continue
                    errors.append(f"{provider.name}: {exc}")
                    breaker.record_failure()
                    log.warning("llm_provedor_falhou", provedor=provider.name, erro=str(exc))
                    break
                breaker.record_success()
                if self.cache is not None:
                    self.cache.set(
                        key,
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
        raise LLMUnavailable(
            "Nenhum provedor de LLM respondeu: " + "; ".join(errors or ["nenhum configurado"])
        )
