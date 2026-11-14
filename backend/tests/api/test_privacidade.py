"""Direitos do titular (localizar, exportar, excluir) e retenção pela API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from radar.db.models import AuditLog, Conversation, Message, PiiIndexEntry
from radar.taxonomy import Role
from radar.testing import AccountFactory

URL = "/api/v1/privacy"
CPF = "529.982.247-25"
ROBERTO = (
    "10/01/2024 09:00 - Roberto Lima: Oi, quanto custa o consórcio?\n"
    "10/01/2024 09:02 - Carla Mendes: Bom dia! Posso simular, me passa seu CPF?\n"
    f"10/01/2024 09:05 - Roberto Lima: Meu CPF é {CPF}\n"
)
# Outra conversa em que o CPF do Roberto aparece (a esposa manda o CPF dele).
MARIA = (
    "11/01/2024 10:00 - Maria Souza: Oi, quero fazer no nome do meu marido\n"
    f"11/01/2024 10:01 - Maria Souza: O CPF dele é {CPF}\n"
    "11/01/2024 10:02 - Carla Mendes: Perfeito, vou simular!\n"
)


def _import(client: TestClient, headers: dict[str, str], chat: str, customer: str) -> uuid.UUID:
    name = f"Conversa do WhatsApp com {customer}.txt"
    response = client.post(
        "/api/v1/imports", headers=headers, files=[("files", (name, chat.encode()))]
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()[0]["conversation_id"])


def _actions(db: Session, tenant_id: uuid.UUID) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.tenant_id == tenant_id)))


# ---------------------------------------------------------------- localizar
def test_localiza_titular_pelo_nome_e_pelo_cpf(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    roberto = _import(client, admin.headers, ROBERTO, "Roberto Lima")
    maria = _import(client, admin.headers, MARIA, "Maria Souza")

    response = client.post(
        f"{URL}/subjects/search",
        headers=admin.headers,
        json={"identifiers": ["Roberto Lima", CPF]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    found = {item["conversation_id"]: item for item in body["conversations"]}
    assert set(found) == {str(roberto), str(maria)}
    assert found[str(roberto)]["relation"] == "participante"
    assert found[str(roberto)]["mentions"] == 1
    assert found[str(maria)]["relation"] == "mencionado"
    assert found[str(maria)]["mentions"] == 1
    assert found[str(maria)]["customer_label"].startswith("Cliente ")
    # A resposta não devolve o identificador procurado nem nomes em claro.
    assert CPF not in response.text
    assert "Roberto" not in response.text

    (entry,) = [a for a in _actions(db, admin.tenant.id) if a.action == "privacy.subject_searched"]
    assert entry.details == {"identificadores": 2, "conversas": 2}


def test_busca_aceita_o_mesmo_dado_em_outro_formato(
    client: TestClient, make_account: AccountFactory
):
    admin = make_account(Role.ADMIN)
    _import(client, admin.headers, ROBERTO, "Roberto Lima")

    body = client.post(
        f"{URL}/subjects/search", headers=admin.headers, json={"identifiers": ["52998224725"]}
    ).json()

    assert len(body["conversations"]) == 1


def test_titular_de_outra_empresa_nao_aparece(client: TestClient, make_account: AccountFactory):
    mine = make_account(Role.ADMIN)
    other = make_account(Role.ADMIN)
    _import(client, other.headers, ROBERTO, "Roberto Lima")

    body = client.post(
        f"{URL}/subjects/search", headers=mine.headers, json={"identifiers": [CPF]}
    ).json()

    assert body["conversations"] == []


def test_so_quem_administra_privacidade_acessa(client: TestClient, make_account: AccountFactory):
    for role in (Role.GESTOR, Role.AUDITOR, Role.VENDEDOR):
        account = make_account(role)
        response = client.post(
            f"{URL}/subjects/search", headers=account.headers, json={"identifiers": [CPF]}
        )
        assert response.status_code == 403, role


def test_identificador_vazio_ou_curto_e_recusado(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    for identifiers in ([], ["ab"], ["x" * 400]):
        response = client.post(
            f"{URL}/subjects/search", headers=admin.headers, json={"identifiers": identifiers}
        )
        assert response.status_code == 422, identifiers


# ---------------------------------------------------------------- exportar
def test_exporta_os_dados_do_titular(client: TestClient, make_account: AccountFactory, db: Session):
    admin = make_account(Role.ADMIN)
    roberto = _import(client, admin.headers, ROBERTO, "Roberto Lima")
    maria = _import(client, admin.headers, MARIA, "Maria Souza")

    response = client.post(
        f"{URL}/subjects/export",
        headers=admin.headers,
        json={"identifiers": ["Roberto Lima", CPF]},
    )

    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    conversations = {c["id"]: c for c in body["conversas"]}
    # Conversa em que o titular participa: vai inteira, com o texto original.
    own = conversations[str(roberto)]
    assert own["relacao"] == "participante"
    assert [m["texto"] for m in own["mensagens"]][-1] == f"Meu CPF é {CPF}"
    assert len(own["mensagens"]) == 3
    # Conversa de outra pessoa que só menciona o titular: só as mensagens com o dado dele, e
    # mascaradas (o resto do texto pode ter dados de terceiros).
    other = conversations[str(maria)]
    assert other["relacao"] == "mencionado"
    assert [m["texto"] for m in other["mensagens"]] == ["O CPF dele é [CPF]"]
    assert other["mensagens"][0]["dados_do_titular"] == ["CPF"]
    assert "Maria" not in str(other)

    (entry,) = [a for a in _actions(db, admin.tenant.id) if a.action == "privacy.subject_exported"]
    assert CPF not in str(entry.details)
    assert entry.details["conversas"] == 2


# ---------------------------------------------------------------- excluir
def test_exclusao_exige_confirmacao(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    response = client.post(
        f"{URL}/subjects/delete", headers=admin.headers, json={"identifiers": [CPF]}
    )
    assert response.status_code == 422


def test_exclui_conversas_do_titular_e_apaga_o_dado_onde_ele_e_mencionado(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    roberto = _import(client, admin.headers, ROBERTO, "Roberto Lima")
    maria = _import(client, admin.headers, MARIA, "Maria Souza")

    response = client.post(
        f"{URL}/subjects/delete",
        headers=admin.headers,
        json={"identifiers": ["Roberto Lima", CPF], "confirm": True},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"conversations_deleted": 1, "messages_redacted": 1}
    db.expire_all()
    assert db.get(Conversation, roberto) is None
    assert db.get(Conversation, maria) is not None
    mention = db.scalars(
        select(Message).where(Message.conversation_id == maria, Message.position == 1)
    ).one()
    assert mention.text_raw is None
    assert mention.text_masked == "O CPF dele é [CPF]"
    untouched = db.scalars(
        select(Message).where(Message.conversation_id == maria, Message.position == 0)
    ).one()
    assert untouched.text_raw == "Oi, quero fazer no nome do meu marido"
    # O índice não aponta mais para o titular.
    search = client.post(
        f"{URL}/subjects/search", headers=admin.headers, json={"identifiers": [CPF]}
    ).json()
    assert search["conversations"] == []
    assert (
        db.scalars(select(PiiIndexEntry).where(PiiIndexEntry.conversation_id == roberto)).all()
        == []
    )

    (entry,) = [a for a in _actions(db, admin.tenant.id) if a.action == "privacy.subject_deleted"]
    assert entry.details == {
        "identificadores": 2,
        "conversas_excluidas": 1,
        "mensagens_anonimizadas": 1,
    }


# ---------------------------------------------------------------- retenção
def test_retencao_pela_api_simula_e_aplica(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, ROBERTO, "Roberto Lima")
    db.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id)
        .values(created_at=datetime.now(UTC) - timedelta(days=120))
    )
    db.commit()

    preview = client.get(f"{URL}/retention", headers=admin.headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["policy"]["retention_raw_days"] == 90
    assert preview.json()["pending"]["raw_messages_purged"] == 3
    assert preview.json()["pending"]["dry_run"] is True

    applied = client.post(f"{URL}/retention/run", headers=admin.headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["raw_messages_purged"] == 3
    assert applied.json()["dry_run"] is False

    db.expire_all()
    messages = db.scalars(select(Message).where(Message.conversation_id == conversation_id)).all()
    assert all(m.text_raw is None for m in messages)
    actions = [a.action for a in _actions(db, admin.tenant.id)]
    assert "privacy.retention_run" in actions


def test_gestor_nao_roda_retencao(client: TestClient, make_account: AccountFactory):
    gestor = make_account(Role.GESTOR)
    assert client.post(f"{URL}/retention/run", headers=gestor.headers).status_code == 403
