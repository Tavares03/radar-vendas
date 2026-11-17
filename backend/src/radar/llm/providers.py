"""Provedores de LLM: todos falam o protocolo ``/chat/completions`` da OpenAI (Groq, Gemini,
OpenRouter e Ollama), então um único cliente HTTP atende todos."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

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
    """Falha de um provedor. ``retryable`` diz se vale tentar de novo no mesmo provedor.

    ``retry_after`` vem do cabeçalho ``Retry-After`` de um 429: quanto o provedor pediu para
    esperar (em segundos).
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None  # ausente ou em formato de data: o roteador usa o backoff padrão
    return value if value >= 0 else None


def _error_detail(response: httpx.Response) -> str:
    """Código ou mensagem curta do erro devolvido pelo provedor (nunca o corpo inteiro)."""
    try:
        data: Any = response.json()
    except ValueError:
        return ""
    if isinstance(data, list) and data:  # o Gemini devolve [{"error": {...}}]
        data = data[0]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        code = error.get("code")  # Groq/OpenRouter: texto ("invalid_api_key"); Gemini: número
        detail = (
            (code if isinstance(code, str) else "")
            or error.get("status")
            or error.get("message")
            or ""
        )
    else:
        detail = error or ""
    return " ".join(str(detail).split())[:120]


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
        extra_body: Mapping[str, object] | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.local = local
        self.limiter = RateLimiter(requests_per_minute, tokens_per_minute)
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http or httpx.Client(timeout=timeout)
        #: Parâmetros próprios do provedor (ex.: ``reasoning_effort`` dos modelos gpt-oss).
        self._extra = dict(extra_body or {})
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
            **self._extra,
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
            detail = _error_detail(response)
            raise ProviderError(
                f"HTTP {response.status_code}" + (f" ({detail})" if detail else ""),
                retryable=retryable,
                status=response.status_code,
                retry_after=_retry_after(response) if response.status_code == 429 else None,
            )
        try:
            data = response.json()
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("resposta em formato inesperado", retryable=False) from exc
        if choice.get("finish_reason") == "length":
            # JSON cortado no meio: "consertar" aceitaria uma análise incompleta como se fosse
            # inteira (objeções e pedidos somem). Melhor ir para o próximo provedor.
            raise ProviderError(
                f"resposta cortada no limite de {max_tokens} tokens", retryable=False
            )
        usage = data.get("usage") or {}
        return ChatResult(
            text=str(text),
            provider=self.name,
            model=self.model,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )
