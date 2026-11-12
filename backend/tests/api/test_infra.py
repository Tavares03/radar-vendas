"""Saúde, cabeçalhos, id de requisição e configuração."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from radar.config import DEV_SECRET_KEY, Settings
from radar.privacy.crypto import (
    decrypt_text,
    encrypt_text,
    normalize_identifier,
    pseudonym,
    subject_hash,
)
from radar.testing import AccountFactory


def test_health_e_ready(client: TestClient):
    health = client.get("/api/health")
    ready = client.get("/api/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] == "ok"


def test_respostas_levam_id_de_requisicao_e_cabecalhos_de_seguranca(client: TestClient):
    generated = client.get("/api/health")
    echoed = client.get("/api/health", headers={"X-Request-ID": "pedido-do-cliente-123"})
    rejected = client.get("/api/health", headers={"X-Request-ID": "id com espaco <script>"})

    assert len(generated.headers["x-request-id"]) == 32
    assert echoed.headers["x-request-id"] == "pedido-do-cliente-123"
    assert rejected.headers["x-request-id"] != "id com espaco <script>"
    assert generated.headers["x-content-type-options"] == "nosniff"
    assert generated.headers["x-frame-options"] == "DENY"
    assert generated.headers["cache-control"] == "no-store"


def test_rota_inexistente_usa_o_formato_padrao_de_erro(client: TestClient):
    response = client.get("/api/v1/nao-existe")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_openapi_documenta_as_rotas(client: TestClient):
    schema = client.get("/api/openapi.json").json()

    assert schema["info"]["title"] == "Radar de Vendas API"
    assert "/api/v1/auth/login" in schema["paths"]


def test_metricas_contam_requisicoes_por_rota_e_nao_por_id(
    client: TestClient, make_account: AccountFactory
):
    account = make_account()
    client.get("/api/v1/sellers", headers=account.headers)
    client.delete(f"/api/v1/sellers/{uuid.uuid4()}", headers=account.headers)
    client.get("/api/v1/caminho-que-nao-existe")

    body = client.get("/api/metrics").text

    assert 'radar_http_requests_total{method="GET",route="/api/v1/sellers",status="200"}' in body
    assert (
        'radar_http_requests_total{method="DELETE",route="/api/v1/sellers/{seller_id}",status="404"}'
        in body
    )
    assert 'route="nao_roteado",status="404"' in body
    assert "caminho-que-nao-existe" not in body


# --------------------------------------------------------------------------- configuração
def test_producao_recusa_o_segredo_de_desenvolvimento():
    with pytest.raises(ValidationError, match="RADAR_SECRET_KEY"):
        Settings(_env_file=None, environment="prod", secret_key=DEV_SECRET_KEY)  # type: ignore[call-arg]


def test_producao_aceita_segredo_proprio():
    settings = Settings(_env_file=None, environment="prod", secret_key="s" * 48)  # type: ignore[call-arg]

    assert settings.json_logs is True


def test_listas_vem_separadas_por_virgula(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RADAR_LLM_PROVIDERS", "ollama, groq")
    monkeypatch.setenv("RADAR_CORS_ORIGINS", "https://a.example.com,https://b.example.com")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.llm_providers == ["ollama", "groq"]
    assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]


def test_chave_de_llm_aceita_nome_com_e_sem_prefixo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "chave-sem-prefixo")
    assert Settings(_env_file=None).groq_api_key.get_secret_value() == "chave-sem-prefixo"  # type: ignore[call-arg, union-attr]

    monkeypatch.setenv("RADAR_GROQ_API_KEY", "chave-com-prefixo")
    assert Settings(_env_file=None).groq_api_key.get_secret_value() == "chave-com-prefixo"  # type: ignore[call-arg, union-attr]


# --------------------------------------------------------------------------- cifragem
def test_texto_cifrado_nao_contem_o_original_e_volta_igual():
    original = "Meu CPF é 529.982.247-25 e moro na Rua das Acácias, 120 🙂"

    stored = encrypt_text(original)

    assert stored.startswith("enc:v1:")
    assert "529.982.247-25" not in stored
    assert decrypt_text(stored) == original
    assert encrypt_text(original) != stored  # IV aleatório: nunca repete


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("529.982.247-25", "52998224725"),
        ("+55 (11) 98765-4321", "11987654321"),
        ("Maria.Silva@Example.com ", "maria.silva@example.com"),
        ("João  da Silva", "joao da silva"),
    ],
)
def test_identificadores_equivalentes_geram_o_mesmo_hash(a: str, b: str, make_tenant):
    tenant = make_tenant()

    assert normalize_identifier(a) == normalize_identifier(b)
    assert subject_hash(tenant.id, a) == subject_hash(tenant.id, b)


def test_hash_de_titular_muda_de_uma_empresa_para_outra(make_tenant):
    tenant_a, tenant_b = make_tenant(), make_tenant()

    assert subject_hash(tenant_a.id, "52998224725") != subject_hash(tenant_b.id, "52998224725")
    assert pseudonym(tenant_a.id, "11987654321").startswith("Cliente ")
    assert "11987654321" not in pseudonym(tenant_a.id, "11987654321")
