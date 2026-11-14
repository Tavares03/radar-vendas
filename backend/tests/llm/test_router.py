"""Camada de LLM: failover, retry, circuit breaker, limite de taxa, cache e saída estruturada."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from radar.config import Settings
from radar.llm import (
    ChatResult,
    FileCache,
    LLMRouter,
    LLMUnavailable,
    OpenAICompatibleProvider,
    ProviderError,
    RateLimiter,
    build_router,
    repair_json,
)


class Answer(BaseModel):
    nota: int
    motivo: str


class FakeProvider:
    def __init__(
        self, name: str, replies: list[str | ProviderError], *, local: bool = False
    ) -> None:
        self.name = name
        self.model = f"{name}-modelo"
        self.local = local
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []
        self.limiter = RateLimiter(requests_per_minute=1000, tokens_per_minute=10**9)

    def chat(self, messages, *, max_tokens, temperature):  # type: ignore[no-untyped-def]
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, ProviderError):
            raise reply
        return ChatResult(
            text=reply, provider=self.name, model=self.model, tokens_in=10, tokens_out=5
        )


def router(*providers: FakeProvider, cache: FileCache | None = None, **kwargs) -> LLMRouter:  # type: ignore[no-untyped-def]
    return LLMRouter(list(providers), cache=cache, sleep=lambda _s: None, **kwargs)


OK = json.dumps({"nota": 8, "motivo": "bom"})


def test_resposta_valida_vira_modelo_pydantic():
    result = router(FakeProvider("a", [OK])).complete_json(system="s", user="u", schema=Answer)
    assert result.value == Answer(nota=8, motivo="bom")
    assert (result.provider, result.tokens_in, result.tokens_out, result.cached) == (
        "a",
        10,
        5,
        False,
    )


def test_falha_temporaria_tenta_de_novo_no_mesmo_provedor():
    provider = FakeProvider("a", [ProviderError("limite", retryable=True), OK])
    result = router(provider, max_retries=2).complete_json(system="s", user="u", schema=Answer)
    assert result.value.nota == 8
    assert len(provider.calls) == 2


def test_failover_para_o_proximo_provedor():
    first = FakeProvider("a", [ProviderError("fora do ar", retryable=False)])
    second = FakeProvider("b", [OK])
    result = router(first, second).complete_json(system="s", user="u", schema=Answer)
    assert result.provider == "b"


def test_json_quebrado_e_consertado_localmente():
    messy = 'Claro! ```json\n{"nota": 7, "motivo": "ok",}\n```'
    result = router(FakeProvider("a", [messy])).complete_json(system="s", user="u", schema=Answer)
    assert result.value.nota == 7


def test_schema_errado_pede_reparo_ao_modelo():
    provider = FakeProvider("a", ['{"nota": "dez"}', OK])
    result = router(provider).complete_json(system="s", user="u", schema=Answer)
    assert result.value.nota == 8
    repair_prompt = provider.calls[1][-1]["content"]
    assert "nota" in repair_prompt
    assert "JSON" in repair_prompt


def test_todos_fora_do_ar():
    providers = [FakeProvider(n, [ProviderError("x", retryable=False)]) for n in "ab"]
    with pytest.raises(LLMUnavailable) as caught:
        router(*providers).complete_json(system="s", user="u", schema=Answer)
    assert "a" in str(caught.value)
    assert "b" in str(caught.value)


def test_circuit_breaker_pula_provedor_que_vem_falhando():
    failing = FakeProvider("a", [ProviderError("x", retryable=False)] * 10)
    backup = FakeProvider("b", [OK] * 10)
    llm = router(failing, backup, breaker_threshold=2)
    for _ in range(4):
        llm.complete_json(system="s", user=f"u{_}", schema=Answer)
    assert len(failing.calls) == 2  # depois de 2 falhas o circuito abriu


def test_limite_de_taxa_por_provedor():
    clock = [0.0]
    limiter = RateLimiter(requests_per_minute=2, tokens_per_minute=10**6, clock=lambda: clock[0])
    assert limiter.wait_time(100) == 0
    limiter.consume(100)
    limiter.consume(100)
    assert limiter.wait_time(100) > 0
    clock[0] += 60
    assert limiter.wait_time(100) == 0


def test_provedor_no_limite_e_pulado_em_vez_de_esperar_muito():
    busy = FakeProvider("a", [OK])
    busy.limiter = RateLimiter(requests_per_minute=1, tokens_per_minute=10**6)
    busy.limiter.consume(1)
    free = FakeProvider("b", [OK])
    result = router(busy, free, max_wait_seconds=1).complete_json(
        system="s", user="u", schema=Answer
    )
    assert result.provider == "b"


def test_cache_evita_segunda_chamada(tmp_path: Path):
    provider = FakeProvider("a", [OK])
    cache = FileCache(tmp_path, ttl_seconds=3600)
    llm = router(provider, cache=cache)
    llm.complete_json(system="s", user="u", schema=Answer)
    again = llm.complete_json(system="s", user="u", schema=Answer)
    assert again.cached is True
    assert len(provider.calls) == 1


def test_texto_sem_mascara_nunca_vai_para_provedor_de_nuvem():
    cloud = FakeProvider("nuvem", [OK])
    local = FakeProvider("ollama", [OK], local=True)
    result = router(cloud, local).complete_json(
        system="s", user="o cpf do cliente é 529.982.247-25", schema=Answer
    )
    assert result.provider == "ollama"
    assert cloud.calls == []
    with pytest.raises(LLMUnavailable):
        router(FakeProvider("nuvem", [OK])).complete_json(
            system="s", user="cpf 529.982.247-25", schema=Answer
        )


def test_reparo_local_de_json():
    assert repair_json('```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}
    assert repair_json('texto antes {"a": "b"} texto depois') == {"a": "b"}


# ---------------------------------------------------------------- HTTP (OpenAI-compatível)
def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="groq",
        base_url="https://api.exemplo/v1",
        api_key="chave",
        model="m",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_provedor_http_le_resposta_e_uso_de_tokens():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert request.headers["authorization"] == "Bearer chave"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": OK}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    result = _provider(handler).chat(
        [{"role": "user", "content": "oi"}], max_tokens=100, temperature=0
    )
    assert (result.text, result.tokens_in, result.tokens_out) == (OK, 120, 30)


def test_provedor_sem_modo_json_tenta_sem_ele():
    seen: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body.get("response_format"))
        if "response_format" in body:
            return httpx.Response(
                400, json={"error": {"message": "response_format is not supported"}}
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": OK}}]})

    provider = _provider(handler)
    assert (
        provider.chat([{"role": "user", "content": "x"}], max_tokens=10, temperature=0).text == OK
    )
    assert seen == [{"type": "json_object"}, None]


def test_erros_http_viram_erro_de_provedor_com_retry_certo():
    for status, retryable in ((429, True), (503, True), (401, False), (400, False)):
        provider = _provider(lambda request, s=status: httpx.Response(s, json={"error": "x"}))
        with pytest.raises(ProviderError) as caught:
            provider.chat([{"role": "user", "content": "x"}], max_tokens=10, temperature=0)
        assert caught.value.retryable is retryable, status


# ---------------------------------------------------------------- montagem pela configuração
def test_modos_cloud_local_e_off():
    settings = Settings(
        _env_file=None,
        llm_mode="cloud",
        groq_api_key="g",
        gemini_api_key=None,
        openrouter_api_key="o",
        ollama_base_url="http://ollama:11434",
    )
    assert [p.name for p in build_router(settings, "cloud").providers] == [
        "groq",
        "openrouter",
        "ollama",
    ]
    assert [p.name for p in build_router(settings, "local").providers] == ["ollama"]
    assert build_router(settings, "off") is None
    no_local = Settings(
        _env_file=None, groq_api_key=None, gemini_api_key=None, openrouter_api_key=None
    )
    assert build_router(no_local, "local") is None
