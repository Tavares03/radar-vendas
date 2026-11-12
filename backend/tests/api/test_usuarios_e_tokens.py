from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.models import ApiToken, AuditLog
from radar.taxonomy import Role
from radar.testing import PASSWORD, AccountFactory

NOVO_USUARIO = {
    "email": "nova.gestora@example.com",
    "name": "Nova Gestora",
    "role": "gestor",
    "password": "senha-bem-forte-1",
}


# --------------------------------------------------------------------------- usuários
def test_admin_cria_usuario_que_consegue_entrar(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)

    created = client.post("/api/v1/users", headers=admin.headers, json=NOVO_USUARIO)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": NOVO_USUARIO["email"], "password": NOVO_USUARIO["password"]},
    )

    assert created.status_code == 201
    assert "password" not in created.json()
    assert "password_hash" not in created.json()
    assert login.status_code == 200
    assert login.json()["user"]["tenant"]["id"] == str(admin.tenant.id)


def test_email_duplicado_e_recusado_mesmo_entre_empresas(
    client: TestClient, make_account: AccountFactory
):
    admin_a = make_account(Role.ADMIN)
    admin_b = make_account(Role.ADMIN)
    client.post("/api/v1/users", headers=admin_a.headers, json=NOVO_USUARIO)

    response = client.post("/api/v1/users", headers=admin_b.headers, json=NOVO_USUARIO)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_senha_curta_e_recusada(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)

    response = client.post(
        "/api/v1/users", headers=admin.headers, json={**NOVO_USUARIO, "password": "curta"}
    )

    assert response.status_code == 422


def test_ultimo_admin_nao_pode_ser_rebaixado_desativado_nem_excluido(
    client: TestClient, make_account: AccountFactory
):
    admin = make_account(Role.ADMIN)
    url = f"/api/v1/users/{admin.user.id}"

    demote = client.patch(url, headers=admin.headers, json={"role": "gestor"})
    deactivate = client.patch(url, headers=admin.headers, json={"is_active": False})
    delete = client.delete(url, headers=admin.headers)

    assert (demote.status_code, deactivate.status_code, delete.status_code) == (400, 400, 400)


def test_admin_redefine_senha_de_outro_usuario(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    vendedor = make_account(Role.VENDEDOR, tenant=admin.tenant)

    response = client.patch(
        f"/api/v1/users/{vendedor.user.id}",
        headers=admin.headers,
        json={"password": "senha-redefinida-9"},
    )

    assert response.status_code == 200
    # A sessão antiga do vendedor cai, a senha antiga não entra e a nova entra.
    assert client.get("/api/v1/auth/me", headers=vendedor.headers).status_code == 401
    old = client.post(
        "/api/v1/auth/login", json={"email": vendedor.user.email, "password": PASSWORD}
    )
    new = client.post(
        "/api/v1/auth/login", json={"email": vendedor.user.email, "password": "senha-redefinida-9"}
    )
    assert (old.status_code, new.status_code) == (401, 200)


def test_alteracoes_ficam_na_auditoria_sem_a_senha(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    created = client.post("/api/v1/users", headers=admin.headers, json=NOVO_USUARIO).json()
    client.patch(
        f"/api/v1/users/{created['id']}",
        headers=admin.headers,
        json={"name": "Nome Novo", "password": "senha-redefinida-9"},
    )

    entries = db.scalars(
        select(AuditLog).where(AuditLog.resource_id == created["id"]).order_by(AuditLog.created_at)
    ).all()

    assert [e.action for e in entries] == ["user.created", "user.updated"]
    assert entries[1].actor_label == admin.user.email
    assert entries[1].details == {"campos": ["name"]}
    assert "senha-redefinida-9" not in str([e.details for e in entries])


# --------------------------------------------------------------------------- tokens de API
def _create_token(client: TestClient, headers: dict[str, str], **body: object) -> dict:
    payload = {"name": "CRM", "scopes": ["read"], **body}
    response = client.post("/api/v1/api-tokens", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_token_de_api_aparece_uma_vez_e_so_o_hash_e_guardado(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)

    created = _create_token(client, admin.headers)
    listed = client.get("/api/v1/api-tokens", headers=admin.headers).json()

    assert created["token"].startswith("rdr_")
    assert "token" not in listed[0]
    stored = db.scalar(select(ApiToken))
    assert stored is not None
    assert created["token"] not in (stored.token_hash, stored.prefix)
    assert len(stored.token_hash) == 64


def test_token_autentica_por_bearer_e_por_x_api_key(
    client: TestClient, make_account: AccountFactory
):
    admin = make_account(Role.ADMIN)
    token = _create_token(client, admin.headers)["token"]

    bearer = client.get("/api/v1/sellers", headers={"Authorization": f"Bearer {token}"})
    header = client.get("/api/v1/sellers", headers={"X-API-Key": token})

    assert (bearer.status_code, header.status_code) == (200, 200)


def test_escopo_do_token_limita_o_que_ele_faz(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    token = _create_token(client, admin.headers, scopes=["read"])["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/tenant", headers=headers).status_code == 200
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    assert (
        client.post("/api/v1/sellers", headers=headers, json={"display_name": "X"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/api-tokens", headers=headers, json={"name": "n", "scopes": ["read"]}
        ).status_code
        == 403
    )


def test_token_revogado_ou_expirado_nao_entra(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    revoked = _create_token(client, admin.headers, name="revogado")
    expired = _create_token(client, admin.headers, name="expirado", expires_in_days=1)
    client.delete(f"/api/v1/api-tokens/{revoked['id']}", headers=admin.headers)
    stored = db.scalar(select(ApiToken).where(ApiToken.name == "expirado"))
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    r1 = client.get("/api/v1/sellers", headers={"Authorization": f"Bearer {revoked['token']}"})
    r2 = client.get("/api/v1/sellers", headers={"Authorization": f"Bearer {expired['token']}"})

    assert (r1.status_code, r2.status_code) == (401, 401)


def test_token_com_segredo_errado_nao_entra(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    token = _create_token(client, admin.headers)["token"]
    forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    response = client.get("/api/v1/sellers", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


def test_token_so_enxerga_a_propria_empresa(client: TestClient, make_account: AccountFactory):
    admin_a = make_account(Role.ADMIN)
    admin_b = make_account(Role.ADMIN)
    client.post("/api/v1/sellers", headers=admin_b.headers, json={"display_name": "Da B"})
    token_a = _create_token(client, admin_a.headers)["token"]

    response = client.get("/api/v1/sellers", headers={"Authorization": f"Bearer {token_a}"})

    assert response.json() == []


# --------------------------------------------------------------------------- empresa
def test_admin_altera_configuracoes_da_empresa(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    current = client.get("/api/v1/tenant", headers=admin.headers).json()
    assert current["settings"]["retention_raw_days"] == 90

    settings = {**current["settings"], "retention_raw_days": 30, "llm_mode": "local"}
    response = client.patch(
        "/api/v1/tenant", headers=admin.headers, json={"name": "Nome Novo", "settings": settings}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Nome Novo"
    assert response.json()["settings"]["retention_raw_days"] == 30
    assert response.json()["settings"]["llm_mode"] == "local"


def test_gestor_nao_altera_configuracoes(client: TestClient, make_account: AccountFactory):
    gestor = make_account(Role.GESTOR)

    response = client.patch("/api/v1/tenant", headers=gestor.headers, json={"name": "Outro"})

    assert response.status_code == 403
