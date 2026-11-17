"""Visão geral da empresa, desempenho por vendedor e a carga da demonstração."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from radar.auth.passwords import verify_password
from radar.cli import app as cli
from radar.config import get_settings
from radar.db.models import Analysis, Conversation, Seller, Tenant, User
from radar.services import demo
from radar.services.accounts import AccountError, create_user, set_password
from radar.services.demo import seed_demo, seed_demo_on_first_boot, shift_days, shift_export
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


def test_tendencia_semanal_nao_encolhe_com_o_periodo(
    client: TestClient, make_account: AccountFactory
):
    admin = make_account(Role.ADMIN)
    six_weeks_before = PROMISE.replace("11/03/2025", "04/02/2025")
    _import(client, admin.headers, six_weeks_before, "Roberto Lima")
    _import(client, admin.headers, GOOD, "Ana Souza")

    body = client.get("/api/v1/overview", headers=admin.headers, params={"days": 30}).json()

    assert body["conversations_analyzed"] == 1  # a nota média é só do período
    assert len(body["weekly"]) == 8
    assert sum(w["conversations"] for w in body["weekly"]) == 2  # o gráfico mostra as 8 semanas
    assert sum(w["critical_alerts"] for w in body["weekly"]) >= 1


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
    assert tenant.default_playbook == "consorcio"
    emails = set(db.scalars(select(User.email).where(User.tenant_id == tenant.id)))
    assert {"admin@demo.radar", "gestor@demo.radar", "vendedor@demo.radar"} <= emails

    conversations = list(
        db.scalars(select(Conversation).where(Conversation.tenant_id == tenant.id))
    )
    assert len(conversations) >= 40
    analyses = db.scalar(
        select(func.count()).select_from(Analysis).where(Analysis.tenant_id == tenant.id)
    )
    assert analyses == len(conversations)

    # A equipe é cadastrada antes da importação: ninguém fica "a confirmar" nem vira vendedor avulso.
    sellers = {
        s.id: s.display_name
        for s in db.scalars(select(Seller).where(Seller.tenant_id == tenant.id))
    }
    assert len(sellers) == 5
    assert {c.seller_id for c in conversations} == set(sellers)
    assert {c.role_confidence for c in conversations} == {"alta"}
    seller_user = db.scalar(select(User).where(User.email == "vendedor@demo.radar"))
    assert seller_user is not None
    assert sellers[seller_user.seller_id] == seller_user.name == "Vera Nunes"

    # As datas acompanham o dia da carga: tudo nas últimas semanas, nada no futuro.
    now = datetime.now(UTC)
    last = [c.last_message_at.replace(tzinfo=UTC) for c in conversations if c.last_message_at]
    assert max(last) <= now + timedelta(hours=4)  # folga do fuso da empresa
    assert max(last) >= now - timedelta(days=15)
    assert min(last) >= now - timedelta(days=80)

    again = CliRunner().invoke(cli, ["seed-demo", "--password", "senha-da-demo-123"])
    assert again.exit_code == 0
    assert "já existe" in again.output


def test_datas_do_export_andam_em_semanas_inteiras():
    assert shift_days(date(2026, 11, 16), date(2026, 11, 16)) == 0
    assert shift_days(date(2026, 11, 16), date(2026, 11, 22)) == 0
    assert shift_days(date(2026, 11, 16), date(2026, 11, 23)) == 7
    assert shift_days(date(2026, 11, 16), date(2027, 1, 6)) == 49
    assert shift_days(date(2026, 11, 16), date(2026, 11, 15)) == -7

    chat = "28/12/2026 08:15 - Vera Nunes: Bom dia!\nsegunda linha, sem data: 01/01/2020\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Conversa do WhatsApp com Cliente.txt", chat)
        archive.writestr("PTT-20261228-WA0001.opus", b"audio")
    with zipfile.ZipFile(io.BytesIO(shift_export(buffer.getvalue(), 7))) as shifted:
        text = shifted.read("Conversa do WhatsApp com Cliente.txt").decode("utf-8")
        assert shifted.read("PTT-20261228-WA0001.opus") == b"audio"
    assert text == "04/01/2027 08:15 - Vera Nunes: Bom dia!\nsegunda linha, sem data: 01/01/2020\n"
    assert shift_export(buffer.getvalue(), 0) == buffer.getvalue()


def test_demonstracao_na_primeira_subida(db: Session, monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    # Desligada por padrão, e nunca em produção.
    assert seed_demo_on_first_boot(settings) is None
    monkeypatch.setattr(settings, "seed_demo", True)
    monkeypatch.setattr(settings, "environment", "prod")
    assert seed_demo_on_first_boot(settings) is None
    monkeypatch.setattr(settings, "environment", "test")

    password = seed_demo_on_first_boot(settings)

    assert password is not None
    assert len(password) >= 12
    user = db.scalar(select(User).where(User.email == "admin@demo.radar"))
    assert user is not None
    assert verify_password(password, user.password_hash)
    analyzed = db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.analyzed_at.is_not(None))
    )
    assert analyzed is not None
    assert analyzed >= 40
    # Com gente no banco, a segunda subida não cria nada.
    assert seed_demo_on_first_boot(settings) is None


def test_demonstracao_aceita_senha_curta_e_as_demais_contas_nao(
    client: TestClient,
    db: Session,
    make_tenant: Callable[..., Tenant],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    # Pasta de amostras vazia: cria só a empresa e as contas, sem processar conversas.
    monkeypatch.setattr(demo, "samples_dir", lambda _settings: tmp_path)

    assert seed_demo(get_settings(), password="123456").created
    for email, _name, _role in demo.DEMO_USERS:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": "123456"})
        assert login.status_code == 200, login.text
        client.cookies.clear()

    tenant = make_tenant()
    with pytest.raises(AccountError, match="10 caracteres"):
        create_user(
            db,
            tenant_id=tenant.id,
            email="pessoa@example.com",
            name="Pessoa",
            role=Role.ADMIN,
            password="123456",
        )
    admin = db.scalar(select(User).where(User.email == "admin@demo.radar"))
    assert admin is not None
    with pytest.raises(AccountError, match="10 caracteres"):
        set_password(admin, "654321")  # trocar pelo painel segue a regra normal


def test_primeira_subida_com_administrador_proprio_nao_carrega_a_demo(
    db: Session, make_account: AccountFactory, monkeypatch: pytest.MonkeyPatch
):
    make_account(Role.ADMIN)
    settings = get_settings()
    monkeypatch.setattr(settings, "seed_demo", True)
    assert seed_demo_on_first_boot(settings) is None
    assert db.scalar(select(Tenant).where(Tenant.slug == "demonstracao")) is None
