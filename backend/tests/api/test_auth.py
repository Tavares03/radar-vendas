from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.api.rate_limit import MemoryRateLimiter, get_rate_limiter
from radar.config import get_settings
from radar.db.models import AuditLog
from radar.taxonomy import Role
from radar.testing import PASSWORD, AccountFactory


def test_login_devolve_token_e_cookie_httponly(client: TestClient, make_account: AccountFactory):
    account = make_account(Role.GESTOR)

    response = client.post(
        "/api/v1/auth/login", json={"email": account.user.email, "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == account.user.email
    assert body["user"]["role"] == "gestor"
    assert body["user"]["tenant"]["id"] == str(account.tenant.id)
    assert "conversations:read" in body["user"]["permissions"]
    assert "users:manage" not in body["user"]["permissions"]
    cookie = response.headers["set-cookie"]
    assert get_settings().cookie_name in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_login_aceita_email_com_maiusculas(client: TestClient, make_account: AccountFactory):
    account = make_account(Role.ADMIN, email="dona@example.com")

    response = client.post(
        "/api/v1/auth/login", json={"email": "Dona@Example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(account.user.id)


def test_login_com_senha_errada_responde_401_generico_e_audita(
    client: TestClient, make_account: AccountFactory, db: Session
):
    account = make_account(Role.ADMIN)

    wrong = client.post(
        "/api/v1/auth/login", json={"email": account.user.email, "password": "senha-errada-123"}
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "ninguem@example.com", "password": PASSWORD}
    )

    assert wrong.status_code == 401
    assert unknown.status_code == 401
    # Mesma mensagem nos dois casos: não revela se o e-mail existe.
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "unauthorized"
    failed = db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")).all()
    assert len(failed) == 1
    assert failed[0].tenant_id == account.tenant.id


def test_usuario_inativo_nao_entra(client: TestClient, make_account: AccountFactory, db: Session):
    account = make_account(Role.VENDEDOR)
    user = db.merge(account.user)
    user.is_active = False
    db.commit()

    response = client.post(
        "/api/v1/auth/login", json={"email": account.user.email, "password": PASSWORD}
    )

    assert response.status_code == 401
    # E a sessão que já existia deixa de valer.
    assert client.get("/api/v1/auth/me", headers=account.headers).status_code == 401


def test_me_exige_autenticacao(client: TestClient):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_com_token_adulterado(client: TestClient, make_account: AccountFactory):
    account = make_account()

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {account.token}x"})

    assert response.status_code == 401


def test_sessao_por_cookie_funciona(client: TestClient, make_account: AccountFactory):
    account = make_account(Role.AUDITOR)
    client.cookies.set(get_settings().cookie_name, account.token)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["role"] == "auditor"


def test_escrita_por_cookie_vinda_de_outro_site_e_recusada(
    client: TestClient, make_account: AccountFactory
):
    account = make_account(Role.ADMIN)
    client.cookies.set(get_settings().cookie_name, account.token)

    cross = client.post("/api/v1/auth/logout", headers={"Sec-Fetch-Site": "cross-site"})
    same = client.post("/api/v1/auth/logout", headers={"Sec-Fetch-Site": "same-origin"})

    assert cross.status_code == 403
    assert cross.json()["error"]["code"] == "cross_site_request"
    assert same.status_code == 200


def test_trocar_senha_invalida_sessoes_antigas(client: TestClient, make_account: AccountFactory):
    account = make_account(Role.GESTOR)
    nova = "outra-senha-bem-forte"

    response = client.post(
        "/api/v1/auth/change-password",
        headers=account.headers,
        json={"current_password": PASSWORD, "new_password": nova},
    )

    assert response.status_code == 200
    new_token = response.json()["access_token"]
    client.cookies.clear()
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code
        == 200
    )
    relogin = client.post(
        "/api/v1/auth/login", json={"email": account.user.email, "password": nova}
    )
    assert relogin.status_code == 200
    old_password = client.post(
        "/api/v1/auth/login", json={"email": account.user.email, "password": PASSWORD}
    )
    assert old_password.status_code == 401


def test_trocar_senha_exige_senha_atual_correta(client: TestClient, make_account: AccountFactory):
    account = make_account()

    response = client.post(
        "/api/v1/auth/change-password",
        headers=account.headers,
        json={"current_password": "nao-e-esta-senha", "new_password": "outra-senha-bem-forte"},
    )

    assert response.status_code == 401


def test_login_tem_limite_de_tentativas(
    client: TestClient, make_account: AccountFactory, monkeypatch: pytest.MonkeyPatch
):
    account = make_account()
    limit = get_settings().login_rate_limit_per_minute
    limiter = get_rate_limiter()
    assert isinstance(limiter, MemoryRateLimiter)
    limiter.reset()  # descarta o login feito pela fixture
    monkeypatch.setattr(
        limiter, "clock", lambda: 1_800_000_000.0
    )  # relógio parado: sem virada de janela

    statuses = [
        client.post(
            "/api/v1/auth/login", json={"email": account.user.email, "password": "errada-123456"}
        ).status_code
        for _ in range(limit + 1)
    ]

    assert statuses[:limit] == [401] * limit
    assert statuses[limit] == 429
    blocked = client.post(
        "/api/v1/auth/login", json={"email": account.user.email, "password": PASSWORD}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1


def test_signup_fica_desligado_por_padrao(client: TestClient):
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Nova Empresa",
            "name": "Fulana",
            "email": "fulana@example.com",
            "password": "senha-bem-forte-1",
        },
    )

    assert response.status_code == 403


def test_validacao_devolve_erro_no_formato_padrao(client: TestClient):
    response = client.post("/api/v1/auth/login", json={"email": "nao-e-email", "password": "x"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["campo"] == "email"
