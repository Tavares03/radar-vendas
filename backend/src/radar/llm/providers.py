"""Provedores de LLM: todos falam o protocolo ``/chat/completions`` da OpenAI (Groq, Gemini,
OpenRouter e Ollama), então um único cliente HTTP atende todos."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from radar.llm.limits import RateLimiter


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


class ProviderError(RuntimeError):
    """Falha de um provedor. ``retryable`` diz se vale tentar de novo no mesmo provedor."""

    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class Provider(Protocol):
    name: str
    model: str
    #: Roda na própria infraestrutura (nada sai da máquina).
    local: bool
    limiter: RateLimiter

    def chat(
        self, messages: Sequence[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> ChatResult: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        local: bool = False,
        timeout: float = 60.0,
        requests_per_minute: int = 30,
        tokens_per_minute: int = 100_000,
        http: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.local = local
        self.limiter = RateLimiter(requests_per_minute, tokens_per_minute)
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http or httpx.Client(timeout=timeout)
        #: Alguns modelos recusam ``response_format``; descobrimos na primeira chamada.
        self._json_mode = True

    def chat(
        self, messages: Sequence[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> ChatResult:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self._http.post(self._url, json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("tempo esgotado", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"falha de conexão ({type(exc).__name__})", retryable=True) from exc

        if response.status_code == 400 and self._json_mode and "response_format" in response.text:
            self._json_mode = False
            return self.chat(messages, max_tokens=max_tokens, temperature=temperature)
        if response.status_code != 200:
            retryable = response.status_code in (408, 409, 425, 429) or response.status_code >= 500
            raise ProviderError(
                f"HTTP {response.status_code}",
                retryable=retryable,
                status=response.status_code,
            )
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("resposta em formato inesperado", retryable=False) from exc
        usage = data.get("usage") or {}
        return ChatResult(
            text=str(text),
            provider=self.name,
            model=self.model,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )
