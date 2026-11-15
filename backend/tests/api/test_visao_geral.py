"""Visão geral da empresa, desempenho por vendedor e a carga da demonstração."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from radar.cli import app as cli
from radar.db.models import Analysis, Conversation, Tenant, User
from radar.taxonomy import Role
from radar.testing import AccountFactory

PROMISE = (
    "11/03/2025 10:00 - Roberto Lima: Oi, quero saber do consórcio\n"
    "11/03/2025 10:02 - Carla Mendes: Contemplação garantida no terceiro mês!\n"
    "11/03/2025 10:05 - Roberto Lima: Achei caro\n"
)
GOOD = (
    "18/03/2025 10:00 - Ana Souza: Oi, tem consórcio de imóvel?\n"
    "18/03/2025 10:02 - Carla Mendes: Temos! A contemplação é por sorteio ou lance, com taxa de administração de 16%.\n"
    "18/03/2025 10:03 - Ana Souza: Obrigada!\n"
)


def _import(client: TestClient, headers: dict[str, str], chat: str, customer: str) -> None:
    response = client.post(
        "/api/v1/imports",
        headers=headers,
        files=[("files", (f"Conversa do WhatsApp com {customer}.txt", chat.encode()))],
        data={"playbook": "consorcio"},
    )
    assert response.status_code == 201, response.text


def test_visao_geral(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    _import(client, admin.headers, PROMISE, "Roberto Lima")
    _import(client, admin.headers, GOOD, "Ana Souza")

    response = client.get("/api/v1/overview", headers=admin.headers, params={"days": 90})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversations_analyzed"] == 2
    assert 0 < body["average_score"] <= 100
    assert body["open_alerts"]["critico"] >= 1
    assert sum(w["conversations"] for w in body["weekly"]) == 2
    assert body["weekly"] == sorted(body["weekly"], key=lambda w: w["week_start"])
    (seller,) = body["sellers"]
    assert seller["name"] == "Carla Mendes"
    assert seller["conversations"] == 2
    assert seller["critical_alerts"] >= 1
    assert {t["type"] for t in body["alert_types"]} >= {"promessa_indevida"}
    assert body["alert_types"][0]["label"]


def test_desempenho_do_vendedor(client: TestClient, make_account: AccountFactory, db: Session):
    admin = make_account(Role.ADMIN)
    _import(client, admin.headers, PROMISE, "Roberto Lima")
    _import(client, admin.headers, GOOD, "Ana Souza")
    seller_id = db.scalars(select(Conversation.seller_id)).first()

    body = client.get(f"/api/v1/sellers/{seller_id}/performance", headers=admin.headers).json()
    assert body["seller"]["display_name"] == "Carla Mendes"
    assert body["conversations"] == 2
    assert {c["id"] for c in body["criteria"]} >= {"conformidade", "objecoes"}
    assert any(a["type"] == "promessa_indevida" for a in body["alerts_by_type"])
    objection = next(o for o in body["objections"] if o["type"] == "objecao_preco")
    assert objection["total"] == 1
    assert len(body["recent"]) == 2


def test_alertas_em_aberto_contam_todas_as_conversas_nao_so_o_periodo(
    client: TestClient, make_account: AccountFactory
):
    admin = make_account(Role.ADMIN)
    old = PROMISE.replace("11/03/2025", "11/03/2024")  # um ano antes da conversa mais recente
    _import(client, admin.headers, old, "Roberto Lima")
    _import(client, admin.headers, GOOD, "Ana Souza")

    body = client.get("/api/v1/overview", headers=admin.headers, params={"days": 30}).json()

    assert body["conversations_analyzed"] == 1  # o período só conta a conversa recente
    assert body["open_alerts"]["critico"] >= 1  # o alerta antigo continua pedindo atenção
    assert "promessa_indevida" in {t["type"] for t in body["alert_types"]}


def test_vendedor_nao_ve_a_visao_geral_da_empresa(client: TestClient, make_account: AccountFactory):
    vendedor = make_account(Role.VENDEDOR)
    assert client.get("/api/v1/overview", headers=vendedor.headers).status_code == 403


def test_empresa_sem_conversas(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    body = client.get("/api/v1/overview", headers=admin.headers).json()
    assert body["conversations_analyzed"] == 0
    assert body["average_score"] is None
    assert body["sellers"] == []


def test_carga_da_demonstracao(db: Session):
    result = CliRunner().invoke(cli, ["seed-demo", "--password", "senha-da-demo-123"])
    assert result.exit_code == 0, result.output
    tenant = db.scalar(select(Tenant).where(Tenant.slug == "demonstracao"))
    assert tenant is not None
    emails = set(db.scalars(select(User.email).where(User.tenant_id == tenant.id)))
    assert {"admin@demo.radar", "gestor@demo.radar", "vendedor@demo.radar"} <= emails
    conversations = db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.tenant_id == tenant.id)
    )
    assert conversations == 10
    analyses = db.scalar(
        select(func.count()).select_from(Analysis).where(Analysis.tenant_id == tenant.id)
    )
    assert analyses == 10
    again = CliRunner().invoke(cli, ["seed-demo", "--password", "senha-da-demo-123"])
    assert again.exit_code == 0
    assert "já existe" in again.output
