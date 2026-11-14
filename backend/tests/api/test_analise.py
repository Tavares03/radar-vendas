"""Análise de ponta a ponta: importação → análise → alertas → revisão; playbooks da empresa."""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.analysis.llm_analyzer import RespostaLLM
from radar.db.models import Alert, Analysis, Conversation, StageMetric
from radar.llm import ChatResult, LLMRouter, RateLimiter
from radar.services.analysis import set_llm_router
from radar.taxonomy import Role
from radar.testing import AccountFactory

CHAT_NAME = "Conversa do WhatsApp com Roberto Lima.txt"
CHAT = (
    "11/03/2025 10:00 - Roberto Lima: Oi, quero saber do consórcio de carro\n"
    "11/03/2025 10:02 - Carla Mendes: Oi Roberto! Contemplação garantida no terceiro mês, pode confiar\n"
    "11/03/2025 10:05 - Roberto Lima: Me manda uma simulação?\n"
    "11/03/2025 10:07 - Carla Mendes: Meu CPF pra cadastro? brincadeira kkk\n"
)


def _import(
    client: TestClient, headers: dict[str, str], chat: str = CHAT, playbook: str = "consorcio"
) -> str:
    response = client.post(
        "/api/v1/imports",
        headers=headers,
        files=[("files", (CHAT_NAME, chat.encode()))],
        data={"playbook": playbook},
    )
    assert response.status_code == 201, response.text
    return str(response.json()[0]["conversation_id"])


def test_importacao_gera_analise_e_alertas(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers)

    response = client.get(
        f"/api/v1/conversations/{conversation_id}/analysis", headers=admin.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] <= 59
    assert body["layers"] == ["regra", "metrica"]
    assert {c["id"] for c in body["criteria"]} >= {"conformidade", "transparencia"}
    types = {a["type"]: a for a in body["alerts"]}
    assert {"promessa_indevida", "pedido_pendente"} <= set(types)
    promise = types["promessa_indevida"]
    assert promise["severity"] == "critico"
    assert promise["status"] == "aberto"
    assert promise["message_index"] == 1
    assert "garantida" in promise["evidence"].lower()
    assert "Roberto" not in json.dumps(body)  # tudo mascarado

    listing = client.get("/api/v1/conversations", headers=admin.headers).json()["items"][0]
    assert listing["score"] == body["score"]
    assert listing["max_severity"] == "critico"
    assert listing["open_alerts"] == len(body["alerts"])

    stages = {m.stage for m in db.scalars(select(StageMetric)).all()}
    assert {"transcricao", "privacidade", "analise"} <= stages


def test_revisao_de_alerta_sobrevive_a_reanalise(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    gestor = make_account(Role.GESTOR, tenant=admin.tenant)
    conversation_id = _import(client, admin.headers)
    alerts = client.get(
        "/api/v1/alerts", headers=admin.headers, params={"type": "promessa_indevida"}
    ).json()
    (alert,) = alerts["items"]

    reviewed = client.patch(
        f"/api/v1/alerts/{alert['id']}",
        headers=admin.headers,
        json={
            "status": "falso_positivo",
            "note": "era brincadeira combinada",
            "assigned_to_user_id": str(gestor.user.id),
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "falso_positivo"
    assert reviewed.json()["assigned_to"]["id"] == str(gestor.user.id)

    client.post(f"/api/v1/conversations/{conversation_id}/reprocess", headers=admin.headers)

    again = client.get(f"/api/v1/alerts/{alert['id']}", headers=admin.headers).json()
    assert again["status"] == "falso_positivo"
    assert again["review_note"] == "era brincadeira combinada"
    conversation = db.get(Conversation, uuid.UUID(conversation_id))
    assert conversation is not None
    db.refresh(conversation)
    assert conversation.open_alerts == len(
        [
            a
            for a in db.scalars(select(Alert).where(Alert.conversation_id == conversation.id))
            if a.status.value == "aberto"
        ]
    )
    assert (
        len(
            db.scalars(
                select(Analysis).where(
                    Analysis.conversation_id == conversation.id, Analysis.is_current
                )
            ).all()
        )
        == 1
    )


def test_filtros_e_visao_do_vendedor(client: TestClient, make_account: AccountFactory, make_seller):  # type: ignore[no-untyped-def]
    admin = make_account(Role.ADMIN)
    carla = make_seller(admin.tenant, "Carla Mendes")
    other = make_seller(admin.tenant, "Outro Vendedor")
    seller_user = make_account(Role.VENDEDOR, tenant=admin.tenant, seller=other)
    _import(client, admin.headers)

    critical = client.get(
        "/api/v1/alerts", headers=admin.headers, params={"severity": "critico"}
    ).json()
    assert critical["total"] >= 1
    assert all(a["severity"] == "critico" for a in critical["items"])
    assert critical["items"][0]["seller_name"] == carla.display_name
    assert critical["items"][0]["customer_label"].startswith("Cliente ")

    assert client.get("/api/v1/alerts", headers=seller_user.headers).json()["total"] == 0
    alert_id = critical["items"][0]["id"]
    assert client.get(f"/api/v1/alerts/{alert_id}", headers=seller_user.headers).status_code == 404
    assert (
        client.patch(
            f"/api/v1/alerts/{alert_id}", headers=seller_user.headers, json={"status": "resolvido"}
        ).status_code
        == 403
    )


def test_alerta_de_outra_empresa_nao_existe(client: TestClient, make_account: AccountFactory):
    mine = make_account(Role.ADMIN)
    other = make_account(Role.ADMIN)
    _import(client, other.headers)
    alert_id = client.get("/api/v1/alerts", headers=other.headers).json()["items"][0]["id"]
    assert client.get(f"/api/v1/alerts/{alert_id}", headers=mine.headers).status_code == 404
    response = client.patch(
        f"/api/v1/alerts/{alert_id}",
        headers=other.headers,
        json={"assigned_to_user_id": str(mine.user.id)},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- LLM (falso) no pipeline
class FakeProvider:
    name, model, local = "groq", "modelo-teste", False

    def __init__(self) -> None:
        self.limiter = RateLimiter(1000, 10**9)

    def chat(self, messages, *, max_tokens, temperature):  # type: ignore[no-untyped-def]
        reply = RespostaLLM(
            resumo="Vendedor prometeu contemplação e não mandou a simulação.",
            proxima_mensagem="Envie a simulação e explique que a contemplação é por sorteio ou lance.",
        )
        return ChatResult(reply.model_dump_json(), self.name, self.model, 1200, 300)


def test_analise_com_llm_registra_provedor_e_tokens(
    client: TestClient, make_account: AccountFactory, db: Session
):
    set_llm_router(LLMRouter([FakeProvider()], sleep=lambda _s: None))
    try:
        admin = make_account(Role.ADMIN)
        conversation_id = _import(client, admin.headers)
    finally:
        set_llm_router(None, clear=True)

    body = client.get(
        f"/api/v1/conversations/{conversation_id}/analysis", headers=admin.headers
    ).json()
    assert body["layers"][-1] == "llm"
    assert body["summary"].startswith("Vendedor prometeu")
    assert body["suggestion"].startswith("Envie a simulação")
    assert body["llm"]["provider"] == "groq"
    metric = db.scalars(select(StageMetric).where(StageMetric.stage == "analise")).one()
    assert (metric.provider, metric.tokens_in, metric.tokens_out) == ("groq", 1200, 300)


# ---------------------------------------------------------------- playbooks
CUSTOM = """
id: minha-loja
nome: Minha Loja
herda: generico
regras:
  - id: brinde
    tipo: promessa_indevida
    descricao: Prometer brinde que não existe
    termos: ["brinde garantido"]
"""


def test_playbook_da_empresa(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    saved = client.put("/api/v1/playbooks/minha-loja", headers=admin.headers, json={"yaml": CUSTOM})
    assert saved.status_code == 200, saved.text
    assert saved.json()["origin"] == "empresa"
    assert saved.json()["version"] == 1

    listed = {p["slug"]: p for p in client.get("/api/v1/playbooks", headers=admin.headers).json()}
    assert listed["minha-loja"]["origin"] == "empresa"
    assert listed["consorcio"]["origin"] == "padrao"

    tried = client.post(
        "/api/v1/playbooks/minha-loja/test",
        headers=admin.headers,
        json={"messages": [{"sender": "vendedor", "text": "Comprando hoje tem brinde garantido!"}]},
    )
    assert tried.status_code == 200
    assert [h["type"] for h in tried.json()["hits"]] == ["promessa_indevida"]

    chat = "11/03/2025 10:00 - Roberto Lima: Oi\n11/03/2025 10:01 - Carla Mendes: Hoje tem brinde garantido\n"
    conversation_id = _import(client, admin.headers, chat, playbook="minha-loja")
    alerts = client.get(
        f"/api/v1/conversations/{conversation_id}/analysis", headers=admin.headers
    ).json()["alerts"]
    assert "promessa_indevida" in {a["type"] for a in alerts}

    other = make_account(Role.ADMIN)
    assert client.get("/api/v1/playbooks/minha-loja", headers=other.headers).status_code == 404
    assert client.delete("/api/v1/playbooks/minha-loja", headers=admin.headers).status_code == 204
    assert client.delete("/api/v1/playbooks/consorcio", headers=admin.headers).status_code == 400


def test_playbook_invalido_explica_o_erro(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    bad = "id: x\nnome: X\nregras:\n  - {id: a, tipo: inventado, descricao: d, termos: [x]}"
    response = client.put("/api/v1/playbooks/x", headers=admin.headers, json={"yaml": bad})
    assert response.status_code == 422
    assert "tipo" in response.json()["error"]["message"]
    vendedor = make_account(Role.VENDEDOR, tenant=admin.tenant)
    assert (
        client.put(
            "/api/v1/playbooks/x", headers=vendedor.headers, json={"yaml": CUSTOM}
        ).status_code
        == 403
    )
