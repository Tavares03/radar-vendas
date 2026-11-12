"""Permissões por papel e isolamento entre empresas."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.models import Seller, Tenant, User
from radar.db.session import TenantIsolationError, new_session
from radar.taxonomy import Role
from radar.testing import AccountFactory


# --------------------------------------------------------------------------- papéis
@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.ADMIN, 200), (Role.GESTOR, 403), (Role.VENDEDOR, 403), (Role.AUDITOR, 403)],
)
def test_so_admin_gerencia_usuarios(
    client: TestClient, make_account: AccountFactory, role: Role, expected: int
):
    account = make_account(role)

    assert client.get("/api/v1/users", headers=account.headers).status_code == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.ADMIN, 201), (Role.GESTOR, 201), (Role.VENDEDOR, 403), (Role.AUDITOR, 403)],
)
def test_quem_pode_cadastrar_vendedor(
    client: TestClient, make_account: AccountFactory, role: Role, expected: int
):
    account = make_account(role)

    response = client.post(
        "/api/v1/sellers", headers=account.headers, json={"display_name": "Bruno Lima"}
    )

    assert response.status_code == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.ADMIN, 200), (Role.AUDITOR, 200), (Role.GESTOR, 403), (Role.VENDEDOR, 403)],
)
def test_quem_le_auditoria(
    client: TestClient, make_account: AccountFactory, role: Role, expected: int
):
    account = make_account(role)

    assert client.get("/api/v1/audit-logs", headers=account.headers).status_code == expected


def test_erro_de_permissao_diz_o_que_falta(client: TestClient, make_account: AccountFactory):
    account = make_account(Role.VENDEDOR)

    response = client.get("/api/v1/users", headers=account.headers)

    assert response.json()["error"]["code"] == "forbidden"
    assert response.json()["error"]["details"]["permissoes_necessarias"] == ["users:manage"]


def test_vendedor_so_enxerga_o_proprio_cadastro(
    client: TestClient,
    make_account: AccountFactory,
    make_tenant: Callable[..., Tenant],
    make_seller: Callable[..., Seller],
):
    tenant = make_tenant()
    eu = make_seller(tenant, "Carla Mendes")
    make_seller(tenant, "Diego Rocha")
    account = make_account(Role.VENDEDOR, tenant=tenant, seller=eu)

    response = client.get("/api/v1/sellers", headers=account.headers)

    assert [s["display_name"] for s in response.json()] == ["Carla Mendes"]


# --------------------------------------------------------------------------- empresas
def test_listagens_nao_cruzam_empresas(
    client: TestClient,
    make_account: AccountFactory,
    make_seller: Callable[..., Seller],
):
    empresa_a = make_account(Role.ADMIN)
    empresa_b = make_account(Role.ADMIN)
    make_seller(empresa_a.tenant, "Vendedora da A")
    make_seller(empresa_b.tenant, "Vendedor da B")

    sellers_a = client.get("/api/v1/sellers", headers=empresa_a.headers).json()
    users_a = client.get("/api/v1/users", headers=empresa_a.headers).json()

    assert [s["display_name"] for s in sellers_a] == ["Vendedora da A"]
    assert [u["email"] for u in users_a["items"]] == [empresa_a.user.email]
    assert users_a["total"] == 1


def test_id_de_outra_empresa_responde_404(
    client: TestClient,
    make_account: AccountFactory,
    make_seller: Callable[..., Seller],
):
    empresa_a = make_account(Role.ADMIN)
    empresa_b = make_account(Role.ADMIN)
    seller_b = make_seller(empresa_b.tenant, "Vendedor da B")

    patch = client.patch(
        f"/api/v1/sellers/{seller_b.id}", headers=empresa_a.headers, json={"display_name": "Hack"}
    )
    delete = client.delete(f"/api/v1/sellers/{seller_b.id}", headers=empresa_a.headers)
    user = client.patch(
        f"/api/v1/users/{empresa_b.user.id}", headers=empresa_a.headers, json={"name": "Hackeado"}
    )

    assert (patch.status_code, delete.status_code, user.status_code) == (404, 404, 404)
    still = client.get("/api/v1/sellers", headers=empresa_b.headers).json()
    assert [s["display_name"] for s in still] == ["Vendedor da B"]


def test_usuario_nao_pode_ser_ligado_a_vendedor_de_outra_empresa(
    client: TestClient,
    make_account: AccountFactory,
    make_seller: Callable[..., Seller],
):
    empresa_a = make_account(Role.ADMIN)
    empresa_b = make_account(Role.ADMIN)
    seller_b = make_seller(empresa_b.tenant, "Vendedor da B")

    response = client.post(
        "/api/v1/users",
        headers=empresa_a.headers,
        json={
            "email": "novo@example.com",
            "name": "Novo Vendedor",
            "role": "vendedor",
            "password": "senha-bem-forte-1",
            "seller_id": str(seller_b.id),
        },
    )

    assert response.status_code == 409


def test_auditoria_nao_cruza_empresas(client: TestClient, make_account: AccountFactory):
    empresa_a = make_account(Role.ADMIN)
    empresa_b = make_account(Role.ADMIN)
    client.post("/api/v1/sellers", headers=empresa_b.headers, json={"display_name": "Só da B"})

    logs_a = client.get("/api/v1/audit-logs", headers=empresa_a.headers).json()

    assert all(item["actor_label"] == empresa_a.user.email for item in logs_a["items"])
    assert "seller.created" not in {item["action"] for item in logs_a["items"]}


# --------------------------------------------------------------------------- sessão com escopo
def test_sessao_com_escopo_filtra_select_e_get(
    make_tenant: Callable[..., Tenant], make_seller: Callable[..., Seller]
):
    tenant_a, tenant_b = make_tenant(), make_tenant()
    seller_a = make_seller(tenant_a, "A")
    seller_b = make_seller(tenant_b, "B")

    scoped = new_session(tenant_a.id)
    try:
        names = scoped.scalars(select(Seller.display_name)).all()
        assert names == ["A"]
        assert scoped.get(Seller, seller_a.id) is not None
        assert scoped.get(Seller, seller_b.id) is None
    finally:
        scoped.close()


def test_sessao_com_escopo_recusa_gravar_em_outra_empresa(
    make_tenant: Callable[..., Tenant],
):
    tenant_a, tenant_b = make_tenant(), make_tenant()

    scoped = new_session(tenant_a.id)
    try:
        scoped.add(Seller(tenant_id=tenant_b.id, display_name="Intruso"))
        with pytest.raises(TenantIsolationError):
            scoped.flush()
    finally:
        scoped.rollback()
        scoped.close()


def test_sessao_com_escopo_preenche_empresa_automaticamente(
    make_tenant: Callable[..., Tenant], db: Session
):
    tenant = make_tenant()

    scoped = new_session(tenant.id)
    try:
        scoped.add(Seller(display_name="Sem empresa explícita"))
        scoped.commit()
    finally:
        scoped.close()

    saved = db.scalar(select(Seller).where(Seller.display_name == "Sem empresa explícita"))
    assert saved is not None
    assert saved.tenant_id == tenant.id


def test_relacionamento_respeita_o_escopo(
    make_account: AccountFactory, make_seller: Callable[..., Seller], db: Session
):
    """Um vínculo inconsistente no banco não pode vazar o vendedor de outra empresa."""
    empresa_a = make_account(Role.ADMIN)
    empresa_b = make_account(Role.ADMIN)
    seller_b = make_seller(empresa_b.tenant, "Vendedor da B")
    user_a = db.get(User, empresa_a.user.id)
    assert user_a is not None
    user_a.seller_id = seller_b.id  # corrupção simulada, feita por fora da API
    db.commit()

    scoped = new_session(empresa_a.tenant.id)
    try:
        loaded = scoped.get(User, empresa_a.user.id)
        assert loaded is not None
        assert loaded.seller is None
    finally:
        scoped.close()


def test_uuid_inexistente_responde_404(client: TestClient, make_account: AccountFactory):
    account = make_account(Role.ADMIN)

    response = client.delete(f"/api/v1/sellers/{uuid.uuid4()}", headers=account.headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
