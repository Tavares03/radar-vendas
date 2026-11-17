"""Camada de LLM: provedores gratuitos com failover (Groq → Gemini → OpenRouter → Ollama)."""

from __future__ import annotations

from typing import Literal

from radar.analysis.models import LLMUnavailable
from radar.config import Settings, get_settings
from radar.llm.cache import FileCache
from radar.llm.limits import CircuitBreaker, RateLimiter
from radar.llm.providers import ChatResult, OpenAICompatibleProvider, Provider, ProviderError
from radar.llm.router import LLMRouter, StructuredResult, repair_json

Mode = Literal["cloud", "local", "off"]

__all__ = [
    "ChatResult",
    "CircuitBreaker",
    "FileCache",
    "LLMRouter",
    "LLMUnavailable",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderError",
    "RateLimiter",
    "StructuredResult",
    "build_router",
    "repair_json",
]


def _extra_body(name: str, model: str, settings: Settings) -> dict[str, object]:
    """Parâmetros próprios de cada provedor/modelo."""
    if name == "groq" and "gpt-oss" in model and settings.groq_reasoning_effort:
        # Com o esforço padrão (medium) o gpt-oss gasta ~1500 tokens raciocinando e o JSON da
        # análise sai cortado (HTTP 400 json_validate_failed na Groq).
        return {"reasoning_effort": settings.groq_reasoning_effort}
    return {}


def _providers(settings: Settings) -> dict[str, OpenAICompatibleProvider]:
    timeout = settings.llm_timeout_seconds
    found: dict[str, OpenAICompatibleProvider] = {}
    cloud = {
        "groq": (
            settings.groq_api_key,
            settings.groq_base_url,
            settings.groq_model,
            settings.groq_requests_per_minute,
            settings.groq_tokens_per_minute,
        ),
        "gemini": (
            settings.gemini_api_key,
            settings.gemini_base_url,
            settings.gemini_model,
            settings.gemini_requests_per_minute,
            settings.gemini_tokens_per_minute,
        ),
        "openrouter": (
            settings.openrouter_api_key,
            settings.openrouter_base_url,
            settings.openrouter_model,
            settings.openrouter_requests_per_minute,
            settings.openrouter_tokens_per_minute,
        ),
    }
    for name, (secret, base_url, model, rpm, tpm) in cloud.items():
        key = secret.get_secret_value() if secret is not None else ""
        if key:
            found[name] = OpenAICompatibleProvider(
                name=name,
                base_url=base_url,
                api_key=key,
                model=model,
                timeout=timeout,
                requests_per_minute=rpm,
                tokens_per_minute=tpm,
                extra_body=_extra_body(name, model, settings),
            )
    if settings.ollama_base_url:
        # Aceita o endereço com ou sem "/v1" (a documentação já mostrou os dois).
        ollama_url = settings.ollama_base_url.rstrip("/").removesuffix("/v1")
        found["ollama"] = OpenAICompatibleProvider(
            name="ollama",
            base_url=ollama_url + "/v1",
            api_key="",
            model=settings.ollama_model,
            local=True,
            timeout=max(timeout, 180.0),
            requests_per_minute=settings.ollama_requests_per_minute,
            tokens_per_minute=settings.ollama_tokens_per_minute,
        )
    return found


def build_router(settings: Settings | None = None, mode: Mode | None = None) -> LLMRouter | None:
    """Roteador conforme o modo: ``cloud`` (todos), ``local`` (só Ollama) ou ``off`` (nenhum)."""
    settings = settings or get_settings()
    mode = mode or settings.llm_mode
    if mode == "off":
        return None
    available = _providers(settings)
    order = [name for name in settings.llm_providers if name in available]
    if mode == "local":
        order = [name for name in order if available[name].local]
    if not order:
        return None
    cache = FileCache(settings.cache_dir / "llm", ttl_seconds=settings.llm_cache_ttl_seconds)
    return LLMRouter(
        [available[name] for name in order],
        cache=cache,
        max_retries=settings.llm_max_retries,
        max_tokens=settings.llm_max_output_tokens,
        throttle_wait_seconds=settings.llm_throttle_wait_seconds,
    )
