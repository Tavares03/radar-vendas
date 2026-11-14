"""Expansão de paráfrases e conjunto fora de distribuição (LLM simulado por HTTP falso)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from radar.taxonomy import CUSTOMER_LABELS, SELLER_LABELS
from radar_synth.banks import load_bank
from radar_synth.expand import expand_family, validate_variant
from radar_synth.llm import LLMError, OpenAICompatibleClient, parse_json
from radar_synth.ood import generate_ood_conversation


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        name="falso",
        base_url="https://llm.exemplo/v1",
        api_key="chave-de-teste",
        model="modelo-x",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff_seconds=0,
    )


def _reply(content: object) -> httpx.Response:
    body = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})


# ---------------------------------------------------------------- cliente
def test_cliente_envia_o_formato_openai_e_le_a_resposta():
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer chave-de-teste"
        seen.append(json.loads(request.content))
        return _reply({"ok": True})

    assert _client(handler).complete("sistema", "usuário") == '{"ok": true}'
    assert seen[0]["model"] == "modelo-x"
    assert [m["role"] for m in seen[0]["messages"]] == ["system", "user"]  # type: ignore[index]


def test_cliente_tenta_de_novo_quando_o_provedor_limita():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": "limite"})
        return _reply("{}")

    assert _client(handler).complete("s", "u") == "{}"
    assert calls["n"] == 3


def test_cliente_desiste_com_erro_claro():
    client = _client(lambda request: httpx.Response(500, text="falhou"))
    with pytest.raises(LLMError):
        client.complete("s", "u")


def test_json_dentro_de_cerca_de_codigo():
    assert parse_json('Aqui está:\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    with pytest.raises(LLMError):
        parse_json("sem json nenhum")


# ---------------------------------------------------------------- expansão
def test_validacao_de_variante():
    originals = ["Meu CPF é {cpf}", "cpf {cpf}"]
    act = "cliente.envia_dados"
    assert validate_variant("O número do meu CPF: {cpf}", originals, act) is None
    assert validate_variant("Meu CPF é 529.982.247-25", originals, act) is not None  # dado literal
    assert validate_variant("Meu email é {email}", originals, act) is not None  # outro slot
    assert validate_variant("meu cpf é {cpf}", originals, act) is not None  # repetida
    assert validate_variant("{cpf} {inventado}", originals, act) is not None
    negation = ["Não posso garantir a contemplação"]
    assert (
        validate_variant("Garanto que sai logo", negation, "vendedor.negativa_correta") is not None
    )
    assert (
        validate_variant("Ninguém pode garantir data", negation, "vendedor.negativa_correta")
        is None
    )


def test_expansao_de_familia_guarda_so_as_variantes_validas():
    bank = load_bank("consorcio")
    act = bank.acts["vendedor.promessa_indevida"]
    family = act.families[0]

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][1]["content"]
        assert "promessa" in prompt.lower()
        return _reply(
            {
                "variantes": [
                    "Te dou minha palavra que você sai contemplado logo",
                    "Liga no 11 91234-5678 que eu garanto",  # dado pessoal literal: recusada
                    "Te dou minha palavra que você sai contemplado logo",  # repetida
                ]
            }
        )

    new = expand_family(_client(handler), bank, act, family, count=3)
    assert new == ["Te dou minha palavra que você sai contemplado logo"]


def test_variantes_salvas_entram_na_mesma_familia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from radar_synth import banks, expand

    def fake_path(origin: str) -> Path:
        return tmp_path / f"{origin}.yaml"

    monkeypatch.setattr(banks, "expanded_path", fake_path)
    monkeypatch.setattr(expand, "expanded_path", fake_path)
    expand.save_expansions(
        "consorcio",
        {"vendedor.promessa_indevida": {"garantido": ["Te dou minha palavra que sai logo"]}},
    )
    banks.load_bank.cache_clear()
    try:
        act = banks.load_bank("consorcio").acts["vendedor.promessa_indevida"]
        (template,) = [t for t in act.templates if t.text == "Te dou minha palavra que sai logo"]
        assert template.family == "consorcio.vendedor.promessa_indevida.garantido"
    finally:
        banks.load_bank.cache_clear()


# ---------------------------------------------------------------- fora de distribuição
def test_conversa_fora_de_distribuicao_troca_dados_por_falsos_e_valida_rotulos():
    def handler(request: httpx.Request) -> httpx.Response:
        return _reply(
            {
                "mensagens": [
                    {
                        "de": "cliente",
                        "texto": "Oi, meu nome é Joana Prado, quero um seguro",
                        "rotulos": [],
                        "dados_pessoais": [{"tipo": "NOME_PESSOA", "valor": "Joana Prado"}],
                    },
                    {
                        "de": "vendedor",
                        "texto": "Esse seguro cobre absolutamente tudo, garantido",
                        "rotulos": ["promessa_indevida", "objecao_preco"],
                        "dados_pessoais": [],
                    },
                    {
                        "de": "cliente",
                        "texto": "Meu CPF é 123.456.789-00",
                        "rotulos": ["inventado"],
                        "dados_pessoais": [{"tipo": "CPF", "valor": "123.456.789-00"}],
                    },
                ],
                "alertas": [
                    {"tipo": "promessa_indevida", "mensagem": 1},
                    {"tipo": "xyz", "mensagem": 9},
                ],
            }
        )

    conversation = generate_ood_conversation(_client(handler), seed=1, sector="seguros")

    assert conversation.split == "ood"
    assert conversation.generator_version.startswith("llm:falso")
    first, second, third = conversation.messages
    assert "Joana Prado" not in first.text  # nomes e documentos viram dados falsos nossos
    assert first.pii[0].type == "NOME_PESSOA"
    assert first.text[first.pii[0].start : first.pii[0].end] == first.pii[0].value
    assert "123.456.789-00" not in third.text
    assert third.text[third.pii[0].start : third.pii[0].end] == third.pii[0].value
    assert second.labels == ["promessa_indevida"]  # rótulo de cliente em mensagem de vendedor sai
    assert third.labels == []
    assert [(a.type, a.message_index) for a in conversation.expected_alerts] == [
        ("promessa_indevida", 1)
    ]
    for message in conversation.messages:
        allowed = SELLER_LABELS if message.sender == "vendedor" else CUSTOMER_LABELS
        assert set(message.labels) <= allowed
