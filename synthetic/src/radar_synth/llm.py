"""Cliente mínimo para LLMs com API compatível com a da OpenAI (Groq, Gemini, OpenRouter, Ollama).

Usado só pelas ferramentas do dataset (paráfrases e conjunto fora de distribuição). A análise do
Radar usa a camada completa de :mod:`radar.llm`, com failover, cache e limites por provedor.
As chaves vêm da configuração do Radar (``.env`` ou variáveis ``GROQ_API_KEY`` etc.).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

import httpx

from radar.config import Settings, get_settings


class LLMError(RuntimeError):
    """O provedor não respondeu algo utilizável."""


class ChatClient(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str: ...


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 90.0,
        max_retries: int = 4,
        backoff_seconds: float = 4.0,
        temperature: float = 0.9,
        http: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._temperature = temperature
        self._http = http or httpx.Client(timeout=timeout)

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        last_error = ""
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(self._url, json=payload, headers=self._headers)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}"
            else:
                if response.status_code == 200:
                    try:
                        return str(response.json()["choices"][0]["message"]["content"])
                    except (KeyError, IndexError, ValueError) as exc:
                        raise LLMError(f"{self.name}: resposta em formato inesperado") from exc
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in (408, 409, 429) and response.status_code < 500:
                    break
            if attempt < self._max_retries:
                time.sleep(self._backoff * (2**attempt))
        raise LLMError(
            f"{self.name}: falhou depois de {self._max_retries + 1} tentativas ({last_error})"
        )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json(text: str) -> Any:
    """JSON da resposta, tolerando cerca de código e texto em volta."""
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    for candidate in candidates:
        start = min((i for i in (candidate.find("{"), candidate.find("[")) if i >= 0), default=-1)
        if start < 0:
            continue
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
    raise LLMError("a resposta do modelo não tem JSON válido")


def client_for(provider: str, settings: Settings | None = None) -> OpenAICompatibleClient:
    """Cliente de um provedor configurado no ``.env``. Levanta :class:`LLMError` sem chave."""
    settings = settings or get_settings()
    providers: dict[str, tuple[str, Any, str]] = {
        "groq": (settings.groq_base_url, settings.groq_api_key, settings.groq_model),
        "gemini": (settings.gemini_base_url, settings.gemini_api_key, settings.gemini_model),
        "openrouter": (
            settings.openrouter_base_url,
            settings.openrouter_api_key,
            settings.openrouter_model,
        ),
        "ollama": (
            (settings.ollama_base_url or "http://localhost:11434").rstrip("/") + "/v1",
            None,
            settings.ollama_model,
        ),
    }
    if provider not in providers:
        raise LLMError(f"provedor desconhecido: {provider} (use {', '.join(providers)})")
    base_url, secret, model = providers[provider]
    key = secret.get_secret_value() if secret is not None else ""
    if provider != "ollama" and not key:
        raise LLMError(
            f"sem chave para {provider}: defina {provider.upper()}_API_KEY no .env (plano gratuito)"
        )
    return OpenAICompatibleClient(name=provider, base_url=base_url, api_key=key, model=model)
