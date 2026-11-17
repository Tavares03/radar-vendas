"""Cliente HTTP da Evolution API contra as respostas que a Evolution 2.3.7 deu de verdade."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import httpx
import pytest

from radar.integrations.evolution import EvolutionClient, EvolutionError


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> EvolutionClient:
    return EvolutionClient(
        "http://evolution:8080", "chave", http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_estado_de_instancia_inexistente_e_none_tanto_404_quanto_200_sem_state():
    never = _client(
        lambda request: httpx.Response(
            404, json={"status": 404, "error": "Not Found", "response": {"message": ["não existe"]}}
        )
    )
    deleted = _client(lambda request: httpx.Response(200, json={"instance": {"instanceName": "x"}}))
    open_ = _client(
        lambda request: httpx.Response(
            200, json={"instance": {"instanceName": "x", "state": "open"}}
        )
    )

    assert never.state("x") is None
    assert deleted.state("x") is None
    assert open_.state("x") == "open"


def test_chave_errada_e_fora_do_ar_viram_mensagens_que_dizem_o_que_fazer():
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusada")

    with pytest.raises(EvolutionError, match="EVOLUTION_API_KEY"):
        _client(lambda request: httpx.Response(401, json={})).qr_code("x")
    with pytest.raises(EvolutionError, match="--profile whatsapp"):
        _client(offline).qr_code("x")
    assert _client(offline).available() is False


def test_cria_a_instancia_so_para_ler_e_manda_a_chave():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"instance": {"instanceName": "radar-x"}})

    _client(handler).create_instance("radar-x", webhook="http://api:8000/hook/segredo")

    body = json.loads(seen[0].content)
    assert seen[0].headers["apikey"] == "chave"
    assert body["groupsIgnore"] is True
    assert body["readMessages"] is False
    assert body["syncFullHistory"] is False
    assert body["webhook"]["url"] == "http://api:8000/hook/segredo"
    assert "MESSAGES_UPSERT" in body["webhook"]["events"]


def test_qr_code_e_audio_em_base64():
    png = "data:image/png;base64,iVBORw0KGgo="
    audio = base64.b64encode(b"OggS...").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/instance/connect/"):
            return httpx.Response(
                200, json={"pairingCode": None, "code": "2@abc", "base64": png, "count": 1}
            )
        return httpx.Response(200, json={"mimetype": "audio/ogg; codecs=opus", "base64": audio})

    client = _client(handler)
    qr = client.qr_code("x")
    content, mimetype = client.media("x", {"key": {"id": "A1"}, "message": {"audioMessage": {}}})

    assert (qr.image, qr.pairing_code) == (png, None)
    assert (content, mimetype) == (b"OggS...", "audio/ogg; codecs=opus")


def test_desconectar_instancia_que_ja_nao_existe_nao_quebra():
    _client(lambda request: httpx.Response(404, json={})).disconnect("x")
