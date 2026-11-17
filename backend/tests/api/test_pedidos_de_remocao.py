"""O vendedor não some com conversa ruim: pede a remoção e só a gestão decide."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.config import get_settings
from radar.db.models import (
    AuditLog,
    Conversation,
    RemovalRequest,
    Seller,
    Tenant,
    WhatsAppConnection,
)
from radar.integrations.evolution import QrCode, set_evolution_client, webhook_token
from radar.taxonomy import Role
from radar.testing import AccountFactory

URL = "/api/v1/conversations"


@dataclass
class Team:
    seller: Seller
    seller_headers: dict[str, str]
    manager_headers: dict[str, str]


@pytest.fixture
def team(
    make_tenant: Callable[..., Tenant],
    make_seller: Callable[..., Seller],
    make_account: AccountFactory,
) -> Team:
    tenant = make_tenant()
    seller = make_seller(tenant, "Carla Mendes")
    return Team(
        seller,
        make_account(Role.VENDEDOR, tenant=tenant, seller=seller).headers,
        make_account(Role.GESTOR, tenant=tenant).headers,
    )


def _conversation(client: TestClient, team: Team) -> str:
    response = client.post(
        URL,
        headers=team.seller_headers,
        json={
            "customer_name": "Roberto Lima",
            "messages": [
                {"sent_at": "2025-03-11T10:00:00", "sender": "cliente", "text": "Oi"},
                {
                    "sent_at": "2025-03-11T10:02:00",
                    "sender": "vendedor",
                    "text": "Contemplação garantida no primeiro mês!",
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["conversation"]["id"])


def _request(
    client: TestClient,
    team: Team,
    conversation_id: str,
    reason: str = "Conversa pessoal, é minha mãe.",
):
    return client.post(
        f"{URL}/{conversation_id}/removal-request",
        headers=team.seller_headers,
        json={"reason": reason},
    )


def test_vendedor_nao_apaga_conversa_so_pede_a_remocao(client: TestClient, team: Team):
    conversation_id = _conversation(client, team)

    assert client.delete(f"{URL}/{conversation_id}", headers=team.seller_headers).status_code == 403
    created = _request(client, team, conversation_id)
    repeated = _request(client, team, conversation_id)

    assert created.status_code == 201
    assert created.json()["status"] == "pendente"
    assert created.json()["requested_by"]
    assert repeated.status_code == 409
    # Enquanto a gestão não decide, a conversa continua lá, analisada.
    detail = client.get(f"{URL}/{conversation_id}", headers=team.manager_headers).json()
    assert detail["pending_removal"]["reason"] == "Conversa pessoal, é minha mãe."
    assert detail["status"] == "analisada"


def test_gestao_recusa_e_a_conversa_fica(client: TestClient, team: Team, db: Session):
    conversation_id = _conversation(client, team)
    request_id = _request(client, team, conversation_id).json()["id"]

    seller_try = client.post(
        f"/api/v1/removal-requests/{request_id}/approve", headers=team.seller_headers, json={}
    )
    rejected = client.post(
        f"/api/v1/removal-requests/{request_id}/reject",
        headers=team.manager_headers,
        json={"note": "É conversa de venda, fica."},
    )

    assert seller_try.status_code == 403
    assert rejected.status_code == 200
    assert (rejected.json()["status"], rejected.json()["decision_note"]) == (
        "recusado",
        "É conversa de venda, fica.",
    )
    assert client.get(f"{URL}/{conversation_id}", headers=team.manager_headers).status_code == 200
    again = client.post(
        f"/api/v1/removal-requests/{request_id}/approve", headers=team.manager_headers, json={}
    )
    assert again.status_code == 409  # pedido já decidido


def test_gestao_aprova_e_a_conversa_sai_mas_o_pedido_fica_registrado(
    client: TestClient, team: Team, db: Session
):
    conversation_id = _conversation(client, team)
    request_id = _request(client, team, conversation_id).json()["id"]
    pending = client.get("/api/v1/removal-requests", headers=team.manager_headers).json()
    mine = client.get("/api/v1/removal-requests", headers=team.seller_headers).json()

    approved = client.post(
        f"/api/v1/removal-requests/{request_id}/approve",
        headers=team.manager_headers,
        json={"note": "Ok, pessoal."},
    )

    assert [p["id"] for p in pending] == [request_id]
    assert [p["id"] for p in mine] == [request_id]
    assert approved.status_code == 200
    assert approved.json()["status"] == "aprovado"
    assert approved.json()["conversation_id"] is None
    assert "Cliente" in approved.json()["conversation_label"]
    assert client.get(f"{URL}/{conversation_id}", headers=team.manager_headers).status_code == 404
    actions = set(db.scalars(select(AuditLog.action)))
    assert {
        "conversation.removal_requested",
        "conversation.removal_approved",
        "conversation.deleted",
    } <= actions


def test_gestao_excluir_direto_fecha_o_pedido_pendente(client: TestClient, team: Team, db: Session):
    conversation_id = _conversation(client, team)
    _request(client, team, conversation_id)

    assert (
        client.delete(f"{URL}/{conversation_id}", headers=team.manager_headers).status_code == 204
    )

    db.expire_all()
    request = db.scalar(select(RemovalRequest))
    assert request is not None
    assert request.status.value == "aprovado"
    assert "diretamente" in request.decision_note


def test_vendedor_nao_troca_o_playbook_da_propria_conversa(client: TestClient, team: Team):
    conversation_id = _conversation(client, team)

    seller = client.patch(
        f"{URL}/{conversation_id}", headers=team.seller_headers, json={"playbook": "generico"}
    )
    manager = client.patch(
        f"{URL}/{conversation_id}", headers=team.manager_headers, json={"playbook": "generico"}
    )

    assert seller.status_code == 403
    assert manager.status_code == 200


class _Evolution:
    def available(self) -> bool:
        return True

    def create_instance(self, name: str, *, webhook: str) -> None:
        return None

    def qr_code(self, name: str) -> QrCode:
        return QrCode(image="data:image/png;base64,AA==", pairing_code=None)

    def state(self, name: str, *, timeout: float | None = None) -> str | None:
        return None

    def disconnect(self, name: str) -> None:
        return None


@pytest.fixture
def evolution() -> Iterator[None]:
    set_evolution_client(_Evolution())  # type: ignore[arg-type]
    yield
    set_evolution_client(None, clear=True)


def test_aprovar_conversa_do_whatsapp_para_de_capturar_aquele_contato(
    client: TestClient, team: Team, db: Session, evolution: None
):
    client.post(f"/api/v1/whatsapp/sellers/{team.seller.id}/connect", headers=team.seller_headers)
    instance = db.scalar(select(WhatsAppConnection.instance_name))
    hook = f"/api/v1/integrations/evolution/webhook/{webhook_token(get_settings())}"

    def message(message_id: str) -> dict[str, object]:
        return {
            "event": "messages.upsert",
            "instance": instance,
            "data": {
                "key": {
                    "remoteJid": "5511900001111@s.whatsapp.net",
                    "fromMe": False,
                    "id": message_id,
                },
                "message": {"conversation": "oi filho, liga pra mãe"},
                "messageTimestamp": 1_763_000_000,
            },
        }

    client.post(hook, json=message("M1"))
    conversation_id = str(db.scalar(select(Conversation.id)))
    request_id = _request(client, team, conversation_id).json()["id"]
    client.post(
        f"/api/v1/removal-requests/{request_id}/approve",
        headers=team.manager_headers,
        json={"stop_capturing": True},
    )

    after = client.post(hook, json=message("M2")).json()

    assert after["resultado"] == "ignorada:contato_removido"
    assert db.scalar(select(func.count()).select_from(Conversation)) == 0
