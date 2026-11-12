"""Conversas: envio por API, leitura com e sem dados originais, correção e exclusão."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from radar.api.middleware import BodyLimitMiddleware
from radar.config import get_settings
from radar.db.models import AuditLog, Conversation, Import, Message, Seller, Tenant
from radar.db.session import new_session
from radar.taxonomy import Role, SenderRole
from radar.testing import AccountFactory, FakeTranscriber, make_zip

URL = "/api/v1/conversations"
CHAT_NAME = "Conversa do WhatsApp com Roberto Lima.txt"
CHAT = (
    "10/01/2024 09:00 - Roberto Lima: Oi, quanto custa o consórcio?\n"
    "10/01/2024 09:02 - Carla Mendes: Bom dia! Posso te ajudar. Meu e-mail é carla@exemplo.com\n"
    "10/01/2024 09:05 - Roberto Lima: Meu CPF é 529.982.247-25\n"
)


def _payload(**overrides):
    body = {
        "external_id": "crm-123",
        "seller_name": "Carla Mendes",
        "customer_name": "Roberto Lima",
        "customer_phone": "+55 11 91234-5678",
        "messages": [
            {"sent_at": "2024-01-10T09:00:00", "sender": "cliente", "text": "Quanto custa?"},
            {
                "sent_at": "2024-01-10T09:02:00-03:00",
                "sender": "vendedor",
                "text": "A partir de R$ 800",
                "external_id": "m2",
            },
        ],
    }
    body.update(overrides)
    return body


def _import_chat(client: TestClient, headers: dict[str, str], chat: str = CHAT) -> str:
    response = client.post(
        "/api/v1/imports", headers=headers, files=[("files", (CHAT_NAME, chat.encode()))]
    )
    assert response.status_code == 201, response.text
    return response.json()[0]["conversation_id"]


# ---------------------------------------------------------------- envio por API
def test_envio_por_api_cria_conversa(client: TestClient, make_account: AccountFactory, db: Session):
    admin = make_account(Role.ADMIN)

    response = client.post(URL, headers=admin.headers, json=_payload())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert body["new_messages"] == 2
    conversation = body["conversation"]
    assert conversation["source"] == "api"
    assert conversation["external_id"] == "crm-123"
    assert conversation["seller"]["display_name"] == "Carla Mendes"
    assert conversation["customer_label"].startswith("Cliente ")
    assert conversation["message_count"] == 2
    # Sem fuso vale o da empresa (São Paulo): 09:00 → 12:00 UTC.
    assert conversation["started_at"] == "2024-01-10T12:00:00Z"
    assert conversation["last_message_at"] == "2024-01-10T12:02:00Z"
    stored = db.scalars(select(Conversation)).one()
    assert stored.customer_name == "+55 11 91234-5678"


def test_envio_por_api_e_idempotente(client: TestClient, make_account: AccountFactory, db: Session):
    admin = make_account(Role.ADMIN)
    client.post(URL, headers=admin.headers, json=_payload())

    again = client.post(URL, headers=admin.headers, json=_payload()).json()
    assert again["created"] is False
    assert again["new_messages"] == 0
    assert again["duplicate_messages"] == 2

    more = _payload()
    more["messages"].append(
        {"sent_at": "2024-01-10T09:10:00", "sender": "cliente", "text": "Vou pensar"}
    )
    third = client.post(URL, headers=admin.headers, json=more).json()
    assert third["created"] is False
    assert third["new_messages"] == 1
    assert third["conversation"]["message_count"] == 3
    assert db.scalar(select(func.count()).select_from(Conversation)) == 1


def test_envio_por_api_valida_o_corpo(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    assert client.post(URL, headers=admin.headers, json=_payload(messages=[])).status_code == 422
    bad_sender = _payload(messages=[{"sent_at": "2024-01-10T09:00:00", "sender": "robô"}])
    assert client.post(URL, headers=admin.headers, json=bad_sender).status_code == 422
    unknown_seller = _payload(seller_id="00000000-0000-4000-8000-000000000000")
    assert client.post(URL, headers=admin.headers, json=unknown_seller).status_code == 404


# ---------------------------------------------------------------- leitura
def test_leitura_padrao_nao_expoe_texto_original(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    conversation_id = _import_chat(client, admin.headers)

    body = client.get(f"{URL}/{conversation_id}", headers=admin.headers).json()

    assert body["revealed"] is False
    assert body["customer_name"] is None
    assert len(body["messages"]) == 3
    dump = str(body)
    assert "529.982.247-25" not in dump
    assert "Roberto" not in dump
    assert "carla@exemplo.com" not in dump
    assert all(m["revealed"] is False for m in body["messages"])
    assert [m["sender_role"] for m in body["messages"]] == ["cliente", "vendedor", "cliente"]
    assert body["messages"][1]["sender_label"] == "Carla Mendes"
    assert body["messages"][0]["sender_label"].startswith("Cliente ")
    assert all(p["name"] is None for p in body["participants"])


def test_revelar_mostra_o_original_e_fica_auditado(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import_chat(client, admin.headers)

    body = client.get(f"{URL}/{conversation_id}?reveal=true", headers=admin.headers).json()

    assert body["revealed"] is True
    assert body["customer_name"] == "Roberto Lima"
    assert body["messages"][2]["text"] == "Meu CPF é 529.982.247-25"
    assert body["messages"][2]["revealed"] is True
    assert {p["name"] for p in body["participants"]} == {"Roberto Lima", "Carla Mendes"}
    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.resource_id == conversation_id)
    ).all()
    assert "conversation.pii_revealed" in actions


def test_quem_pode_revelar(
    client: TestClient,
    make_account: AccountFactory,
    make_tenant: Callable[..., Tenant],
    db: Session,
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    conversation_id = _import_chat(client, admin.headers)
    seller = db.scalars(select(Seller)).one()
    url = f"{URL}/{conversation_id}?reveal=true"

    assert (
        client.get(url, headers=make_account(Role.GESTOR, tenant=tenant).headers).status_code == 200
    )
    assert (
        client.get(url, headers=make_account(Role.AUDITOR, tenant=tenant).headers).status_code
        == 200
    )
    seller_account = make_account(Role.VENDEDOR, tenant=tenant, seller=seller)
    assert client.get(url, headers=seller_account.headers).status_code == 403
    # Sem revelar, o vendedor lê a própria conversa normalmente.
    assert client.get(f"{URL}/{conversation_id}", headers=seller_account.headers).status_code == 200

    token = client.post(
        "/api/v1/api-tokens", headers=admin.headers, json={"name": "bi", "scopes": ["read"]}
    ).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get(url, headers=bearer).status_code == 403
    assert client.get(f"{URL}/{conversation_id}", headers=bearer).status_code == 200


def test_empresa_pode_restringir_quem_revela(
    client: TestClient, make_account: AccountFactory, make_tenant: Callable[..., Tenant]
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    gestor = make_account(Role.GESTOR, tenant=tenant)
    conversation_id = _import_chat(client, admin.headers)
    settings = client.get("/api/v1/tenant", headers=admin.headers).json()["settings"]
    settings["reveal_roles"] = ["admin"]
    updated = client.patch("/api/v1/tenant", headers=admin.headers, json={"settings": settings})
    assert updated.status_code == 200, updated.text

    url = f"{URL}/{conversation_id}?reveal=true"
    assert client.get(url, headers=gestor.headers).status_code == 403
    assert client.get(url, headers=admin.headers).status_code == 200


def test_vendedor_so_ve_as_proprias_conversas(
    client: TestClient,
    make_account: AccountFactory,
    make_tenant: Callable[..., Tenant],
    make_seller: Callable[..., Seller],
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    carla = make_seller(tenant, "Carla Mendes")
    diego = make_seller(tenant, "Diego Ramos")
    mine = _import_chat(client, admin.headers)
    theirs = client.post(
        URL, headers=admin.headers, json=_payload(seller_name=None, seller_id=str(diego.id))
    ).json()["conversation"]["id"]
    carla_account = make_account(Role.VENDEDOR, tenant=tenant, seller=carla)
    unlinked = make_account(Role.VENDEDOR, tenant=tenant)

    listing = client.get(URL, headers=carla_account.headers).json()
    assert [item["id"] for item in listing["items"]] == [mine]
    assert client.get(f"{URL}/{theirs}", headers=carla_account.headers).status_code == 404
    assert client.get(URL, headers=unlinked.headers).json()["total"] == 0
    assert client.get(f"{URL}/{mine}", headers=unlinked.headers).status_code == 404
    assert client.get(URL, headers=admin.headers).json()["total"] == 2


def test_listagem_filtra_e_pagina(
    client: TestClient,
    make_account: AccountFactory,
    make_seller: Callable[..., Seller],
    make_tenant: Callable[..., Tenant],
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    diego = make_seller(tenant, "Diego Ramos")
    _import_chat(client, admin.headers)
    for index in range(3):
        payload = _payload(
            external_id=f"crm-{index}",
            seller_name=None,
            seller_id=str(diego.id),
            customer_phone=f"+55 11 90000-000{index}",
            messages=[
                {"sent_at": f"2024-02-0{index + 1}T10:00:00", "sender": "cliente", "text": "oi"}
            ],
        )
        assert client.post(URL, headers=admin.headers, json=payload).status_code == 201

    everything = client.get(URL, headers=admin.headers).json()
    assert everything["total"] == 4
    # Mais recente primeiro.
    assert everything["items"][0]["external_id"] == "crm-2"

    by_seller = client.get(f"{URL}?seller_id={diego.id}", headers=admin.headers).json()
    assert by_seller["total"] == 3
    by_source = client.get(f"{URL}?source=whatsapp_export", headers=admin.headers).json()
    assert by_source["total"] == 1
    by_date = client.get(
        f"{URL}?date_from=2024-02-02T00:00:00&date_to=2024-02-02T23:59:59", headers=admin.headers
    ).json()
    assert [item["external_id"] for item in by_date["items"]] == ["crm-1"]
    page = client.get(f"{URL}?limit=2&offset=2", headers=admin.headers).json()
    assert len(page["items"]) == 2
    assert page["total"] == 4


def test_conversas_nao_cruzam_empresas(client: TestClient, make_account: AccountFactory):
    one, two = make_account(Role.ADMIN), make_account(Role.ADMIN)
    conversation_id = _import_chat(client, one.headers)

    assert client.get(URL, headers=two.headers).json()["total"] == 0
    assert client.get(f"{URL}/{conversation_id}", headers=two.headers).status_code == 404
    assert client.delete(f"{URL}/{conversation_id}", headers=two.headers).status_code == 404
    patch = client.patch(f"{URL}/{conversation_id}", headers=two.headers, json={"playbook": "x"})
    assert patch.status_code == 404
    assert client.get(f"{URL}/{conversation_id}", headers=one.headers).status_code == 200


# ---------------------------------------------------------------- correção
def test_corrigir_quem_e_o_vendedor(client: TestClient, make_account: AccountFactory, db: Session):
    admin = make_account(Role.ADMIN)
    chat = "10/01/2024 09:00 - Ana Souza: oi\n10/01/2024 09:01 - Bruno Dias: olá\n"
    conversation_id = _import_chat(client, admin.headers, chat)
    before = client.get(f"{URL}/{conversation_id}", headers=admin.headers).json()
    assert before["role_confidence"] != "alta"
    wrong_customer = next(p for p in before["participants"] if p["role"] == "cliente")

    response = client.patch(
        f"{URL}/{conversation_id}",
        headers=admin.headers,
        json={"seller_participant": wrong_customer["key"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["role_confidence"] == "alta"
    after = client.get(f"{URL}/{conversation_id}?reveal=true", headers=admin.headers).json()
    roles = {p["name"]: p["role"] for p in after["participants"]}
    assert set(roles.values()) == {"vendedor", "cliente"}
    new_seller_name = next(name for name, role in roles.items() if role == "vendedor")
    assert after["seller"]["display_name"] == new_seller_name
    assert after["customer_name"] != new_seller_name
    by_role = dict(
        db.execute(select(Message.sender_role, func.count()).group_by(Message.sender_role)).all()
    )
    assert by_role == {SenderRole.VENDEDOR: 1, SenderRole.CLIENTE: 1}
    assert after["seller_message_count"] == 1

    unknown = client.patch(
        f"{URL}/{conversation_id}", headers=admin.headers, json={"seller_participant": "nada"}
    )
    assert unknown.status_code == 400


def test_trocar_vendedor_e_playbook(
    client: TestClient,
    make_account: AccountFactory,
    make_tenant: Callable[..., Tenant],
    make_seller: Callable[..., Seller],
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    diego = make_seller(tenant, "Diego Ramos")
    conversation_id = _import_chat(client, admin.headers)

    response = client.patch(
        f"{URL}/{conversation_id}",
        headers=admin.headers,
        json={"seller_id": str(diego.id), "playbook": "consorcio"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["seller"]["id"] == str(diego.id)
    assert body["playbook"] == "consorcio"
    detail = client.get(f"{URL}/{conversation_id}", headers=admin.headers).json()
    assert detail["messages"][1]["sender_label"] == "Diego Ramos"


def test_vendedor_nao_troca_o_dono_da_conversa(
    client: TestClient,
    make_account: AccountFactory,
    make_tenant: Callable[..., Tenant],
    db: Session,
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    conversation_id = _import_chat(client, admin.headers)
    seller = db.scalars(select(Seller)).one()
    account = make_account(Role.VENDEDOR, tenant=tenant, seller=seller)

    response = client.patch(
        f"{URL}/{conversation_id}", headers=account.headers, json={"seller_id": str(seller.id)}
    )
    assert response.status_code == 403


def test_reprocessar(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    conversation_id = _import_chat(client, admin.headers)
    response = client.post(f"{URL}/{conversation_id}/reprocess", headers=admin.headers)
    assert response.status_code == 202
    detail = client.get(f"{URL}/{conversation_id}", headers=admin.headers).json()
    assert detail["status"] == "analisada"


# ---------------------------------------------------------------- áudio e exclusão
def _import_with_audio(client: TestClient, headers: dict[str, str]) -> str:
    chat = (
        "10/01/2024 09:00 - Carla Mendes: Bom dia!\n"
        "10/01/2024 09:01 - Roberto Lima: PTT-20240110-WA0001.opus (arquivo anexado)\n"
    )
    archive = make_zip({CHAT_NAME: chat, "PTT-20240110-WA0001.opus": b"OggS-audio"})
    response = client.post(
        "/api/v1/imports", headers=headers, files=[("files", ("export.zip", archive))]
    )
    return response.json()[0]["conversation_id"]


def test_ouvir_audio_exige_permissao_de_revelar(
    client: TestClient,
    make_account: AccountFactory,
    make_tenant: Callable[..., Tenant],
    fake_transcriber: FakeTranscriber,
    db: Session,
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    conversation_id = _import_with_audio(client, admin.headers)
    detail = client.get(f"{URL}/{conversation_id}", headers=admin.headers).json()
    audio = next(m for m in detail["messages"] if m["kind"] == "audio")
    assert audio["has_audio"] is True
    url = f"{URL}/{conversation_id}/messages/{audio['id']}/audio"

    response = client.get(url, headers=admin.headers)
    assert response.status_code == 200
    assert response.content == b"OggS-audio"
    assert response.headers["content-type"] == "audio/ogg"

    seller = db.scalars(select(Seller)).one()
    seller_account = make_account(Role.VENDEDOR, tenant=tenant, seller=seller)
    assert client.get(url, headers=seller_account.headers).status_code == 403
    other = make_account(Role.ADMIN)
    assert client.get(url, headers=other.headers).status_code == 404
    text_message = next(m for m in detail["messages"] if m["kind"] == "texto")
    no_audio = f"{URL}/{conversation_id}/messages/{text_message['id']}/audio"
    assert client.get(no_audio, headers=admin.headers).status_code == 404


def test_excluir_apaga_mensagens_audios_e_importacao(
    client: TestClient,
    make_account: AccountFactory,
    fake_transcriber: FakeTranscriber,
    db: Session,
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import_with_audio(client, admin.headers)
    media_folder = get_settings().media_dir / str(admin.tenant.id) / conversation_id
    assert any(media_folder.iterdir())

    response = client.delete(f"{URL}/{conversation_id}", headers=admin.headers)

    assert response.status_code == 204
    assert client.get(f"{URL}/{conversation_id}", headers=admin.headers).status_code == 404
    assert db.scalar(select(func.count()).select_from(Conversation)) == 0
    assert db.scalar(select(func.count()).select_from(Message)) == 0
    assert db.scalar(select(func.count()).select_from(Import)) == 0
    assert not media_folder.exists()
    assert db.scalars(select(AuditLog).where(AuditLog.action == "conversation.deleted")).one()


def test_quem_pode_excluir(
    client: TestClient, make_account: AccountFactory, make_tenant: Callable[..., Tenant]
):
    tenant = make_tenant()
    admin = make_account(Role.ADMIN, tenant=tenant)
    conversation_id = _import_chat(client, admin.headers)
    auditor = make_account(Role.AUDITOR, tenant=tenant)
    assert client.delete(f"{URL}/{conversation_id}", headers=auditor.headers).status_code == 403
    gestor = make_account(Role.GESTOR, tenant=tenant)
    assert client.delete(f"{URL}/{conversation_id}", headers=gestor.headers).status_code == 204


# ---------------------------------------------------------------- isolamento em agregações
def test_escopo_de_empresa_vale_para_contagens_e_colunas(
    client: TestClient, make_account: AccountFactory
):
    one, two = make_account(Role.ADMIN), make_account(Role.ADMIN)
    _import_chat(client, one.headers)
    client.post(URL, headers=two.headers, json=_payload())

    scoped = new_session(two.tenant.id)
    try:
        assert scoped.scalar(select(func.count()).select_from(Message)) == 2
        assert scoped.scalar(select(func.count(Message.id))) == 2
        assert scoped.scalar(select(func.max(Message.position))) == 1
        assert len(scoped.scalars(select(Message.dedupe_hash)).all()) == 2
        grouped = scoped.execute(
            select(Message.sender_role, func.count()).group_by(Message.sender_role)
        ).all()
        assert sum(count for _, count in grouped) == 2
        joined = scoped.execute(
            select(Conversation.id, func.count(Message.id))
            .join(Message, Message.conversation_id == Conversation.id)
            .group_by(Conversation.id)
        ).all()
        assert len(joined) == 1
    finally:
        scoped.close()


# ---------------------------------------------------------------- limite de corpo
@pytest.fixture
def limited_client() -> TestClient:
    async def echo(request: Request) -> JSONResponse:
        body = await request.body()
        return JSONResponse({"bytes": len(body)})

    app = Starlette(
        routes=[
            Route("/api/v1/imports", echo, methods=["POST"]),
            Route("/x", echo, methods=["POST"]),
        ]
    )
    app.add_middleware(
        BodyLimitMiddleware, default_limit=100, upload_limit=1000, upload_paths=("/api/v1/imports",)
    )
    return TestClient(app)


def test_corpo_acima_do_limite_e_recusado(limited_client: TestClient):
    assert limited_client.post("/x", content=b"a" * 100).json() == {"bytes": 100}
    rejected = limited_client.post("/x", content=b"a" * 101)
    assert rejected.status_code == 413
    assert rejected.json()["error"]["code"] == "payload_too_large"
    assert limited_client.post("/api/v1/imports", content=b"a" * 1000).status_code == 200
    assert limited_client.post("/api/v1/imports", content=b"a" * 1001).status_code == 413


def test_limite_vale_mesmo_sem_content_length(limited_client: TestClient):
    def chunks():
        for _ in range(30):
            yield b"a" * 10

    response = limited_client.post("/x", content=chunks())
    assert response.status_code == 413
