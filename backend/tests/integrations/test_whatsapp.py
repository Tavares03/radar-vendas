"""WhatsApp conectado pela Evolution API: conexão por QR, webhook e análise depois da pausa.

O cliente falso imita as respostas que a Evolution 2.3.7 deu de verdade (QR em data URL, estado
``connecting``/``open``, instância inexistente sem ``state``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.config import get_settings
from radar.db.models import (
    AuditLog,
    Conversation,
    Message,
    Seller,
    Tenant,
    WhatsAppConnection,
)
from radar.integrations.evolution import (
    EvolutionError,
    QrCode,
    set_evolution_client,
    webhook_token,
)
from radar.integrations.whatsapp import contact_of, enqueue_idle_conversations
from radar.services import processing
from radar.taxonomy import (
    ConversationStatus,
    ImportSource,
    Role,
    SenderRole,
    TranscriptionStatus,
)
from radar.testing import AccountFactory, FakeTranscriber

CLIENT_JID = "5511987651234@s.whatsapp.net"
T0 = 1_763_000_000  # segundos (WhatsApp manda o horário em epoch)


@dataclass
class FakeEvolution:
    states: dict[str, str | None] = field(default_factory=dict)
    created: list[tuple[str, str]] = field(default_factory=list)
    disconnected: list[str] = field(default_factory=list)
    media_calls: list[dict[str, Any]] = field(default_factory=list)
    media_fails: bool = False

    def available(self) -> bool:
        return True

    def create_instance(self, name: str, *, webhook: str) -> None:
        self.created.append((name, webhook))
        self.states[name] = "connecting"

    def qr_code(self, name: str) -> QrCode:
        return QrCode(image="data:image/png;base64,iVBORw0KGgo=", pairing_code=None)

    def state(self, name: str, *, timeout: float | None = None) -> str | None:
        return self.states.get(name)

    def disconnect(self, name: str) -> None:
        self.disconnected.append(name)
        self.states.pop(name, None)

    def media(self, name: str, message: dict[str, Any]) -> tuple[bytes, str]:
        self.media_calls.append(message)
        if self.media_fails:
            raise EvolutionError("fora do ar")
        return b"OggS-audio-de-teste", "audio/ogg; codecs=opus"


@pytest.fixture
def evolution() -> Iterator[FakeEvolution]:
    fake = FakeEvolution()
    set_evolution_client(fake)  # type: ignore[arg-type]
    yield fake
    set_evolution_client(None, clear=True)


@dataclass
class Team:
    tenant: Tenant
    seller: Seller
    other: Seller
    seller_headers: dict[str, str]
    manager_headers: dict[str, str]


@pytest.fixture
def team(
    make_tenant: Callable[..., Tenant],
    make_seller: Callable[..., Seller],
    make_account: AccountFactory,
) -> Team:
    tenant = make_tenant("Loja Teste")
    seller = make_seller(tenant, "Carla Mendes")
    other = make_seller(tenant, "Bruno Alves")
    seller_account = make_account(Role.VENDEDOR, tenant=tenant, seller=seller)
    manager = make_account(Role.GESTOR, tenant=tenant)
    return Team(tenant, seller, other, seller_account.headers, manager.headers)


def _connect(client: TestClient, team: Team) -> str:
    response = client.post(
        f"/api/v1/whatsapp/sellers/{team.seller.id}/connect", headers=team.seller_headers
    )
    assert response.status_code == 200, response.text
    return f"/api/v1/integrations/evolution/webhook/{webhook_token(get_settings())}"


def _instance(db: Session, seller: Seller) -> str:
    db.expire_all()
    row = db.scalar(select(WhatsAppConnection).where(WhatsAppConnection.seller_id == seller.id))
    assert row is not None
    return row.instance_name


def _message(
    instance: str,
    message_id: str,
    message: dict[str, Any],
    *,
    from_me: bool = False,
    jid: str = CLIENT_JID,
    at: int = T0,
) -> dict[str, Any]:
    return {
        "event": "messages.upsert",
        "instance": instance,
        "data": {
            "key": {"remoteJid": jid, "fromMe": from_me, "id": message_id},
            "pushName": "Fulano",
            "message": message,
            "messageType": next(iter(message)),
            "messageTimestamp": at,
        },
        "apikey": "token-da-instancia",
    }


def _conversation(db: Session) -> Conversation:
    db.expire_all()
    conversation = db.scalar(select(Conversation))
    assert conversation is not None
    return conversation


# ---------------------------------------------------------------- conexão
def test_vendedor_conecta_o_proprio_numero_pelo_qr_e_nao_o_dos_outros(
    client: TestClient, team: Team, evolution: FakeEvolution
):
    status = client.get("/api/v1/whatsapp", headers=team.seller_headers).json()
    assert (status["enabled"], status["available"], status["can_manage"]) == (True, True, False)
    assert [s["seller"]["display_name"] for s in status["sellers"]] == ["Carla Mendes"]

    response = client.post(
        f"/api/v1/whatsapp/sellers/{team.seller.id}/connect", headers=team.seller_headers
    )

    assert response.status_code == 200
    assert response.json()["state"] == "aguardando_qr"
    assert response.json()["qr_image"].startswith("data:image/png;base64,")
    name, webhook = evolution.created[0]
    assert name.startswith("radar-")
    assert "Carla" not in name  # o nome da instância não carrega dado pessoal
    assert webhook.endswith(webhook_token(get_settings()))
    other = client.post(
        f"/api/v1/whatsapp/sellers/{team.other.id}/connect", headers=team.seller_headers
    )
    assert other.status_code == 403


def test_gestao_ve_a_equipe_e_so_ela_desconecta_pelo_painel(
    client: TestClient, team: Team, evolution: FakeEvolution, db: Session
):
    _connect(client, team)
    evolution.states[_instance(db, team.seller)] = "open"

    status = client.get("/api/v1/whatsapp", headers=team.manager_headers).json()
    by_name = {s["seller"]["display_name"]: s for s in status["sellers"]}
    assert status["can_manage"] is True
    assert by_name["Carla Mendes"]["connection"]["state"] == "conectado"
    assert by_name["Bruno Alves"]["connection"] is None

    url = f"/api/v1/whatsapp/sellers/{team.seller.id}/connection"
    assert client.delete(url, headers=team.seller_headers).status_code == 403
    assert client.delete(url, headers=team.manager_headers).status_code == 204

    db.expire_all()
    row = db.scalar(select(WhatsAppConnection))
    assert row is not None
    assert row.state.value == "desconectado"
    assert row.disconnected_at is not None
    assert evolution.disconnected == [row.instance_name]


def test_sem_evolution_configurada_o_painel_avisa(client: TestClient, team: Team):
    set_evolution_client(None)
    try:
        status = client.get("/api/v1/whatsapp", headers=team.seller_headers).json()
        response = client.post(
            f"/api/v1/whatsapp/sellers/{team.seller.id}/connect", headers=team.seller_headers
        )
    finally:
        set_evolution_client(None, clear=True)
    assert (status["enabled"], status["available"]) == (False, False)
    assert response.status_code == 503
    assert "--profile whatsapp" in response.json()["error"]["message"]


def test_conectar_e_cair_ficam_registrados_para_a_gestao(
    client: TestClient, team: Team, evolution: FakeEvolution, db: Session
):
    hook = _connect(client, team)
    instance = _instance(db, team.seller)

    for state in ("open", "connecting", "close"):
        body = {
            "event": "connection.update",
            "instance": instance,
            "data": {"instance": instance, "state": state, "wuid": "5511999991234@s.whatsapp.net"},
        }
        assert client.post(hook, json=body).status_code == 200
        if state == "connecting":
            db.expire_all()
            # Reconexão rápida de uma sessão aberta não vira "aguardando QR".
            assert db.scalar(select(WhatsAppConnection.state)).value == "conectado"

    db.expire_all()
    row = db.scalar(select(WhatsAppConnection))
    assert row is not None
    assert (row.state.value, row.phone_tail) == ("desconectado", "1234")
    assert row.connected_at is not None
    assert row.disconnected_at is not None
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"whatsapp.connected", "whatsapp.disconnected"} <= actions


def test_webhook_com_token_errado_e_recusado(client: TestClient):
    response = client.post(
        "/api/v1/integrations/evolution/webhook/token-errado", json={"event": "messages.upsert"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- mensagens
def test_mensagens_viram_a_conversa_do_vendedor_e_esperam_a_pausa(
    client: TestClient, team: Team, evolution: FakeEvolution, db: Session
):
    hook = _connect(client, team)
    instance = _instance(db, team.seller)

    client.post(hook, json=_message(instance, "A1", {"conversation": "Oi, quero uma simulação"}))
    client.post(
        hook,
        json=_message(
            instance,
            "A2",
            {"extendedTextMessage": {"text": "Claro! Te mando hoje."}},
            from_me=True,
            at=T0 + 60,
        ),
    )
    repeated = client.post(hook, json=_message(instance, "A1", {"conversation": "Oi"})).json()

    conversation = _conversation(db)
    roles = [m.sender_role for m in db.scalars(select(Message).order_by(Message.sent_at)).all()]
    assert repeated["resultado"] == "repetida"
    assert roles == [SenderRole.CLIENTE, SenderRole.VENDEDOR]
    assert conversation.seller_id == team.seller.id
    assert conversation.status is ConversationStatus.AGUARDANDO
    assert conversation.role_confidence == "alta"
    # O telefone do cliente não aparece em claro na chave da conversa.
    assert conversation.external_id is not None
    assert "987651234" not in conversation.external_id
    assert conversation.started_at == datetime.fromtimestamp(T0, UTC)


def test_grupos_status_e_reacoes_nao_entram(
    client: TestClient, team: Team, evolution: FakeEvolution, db: Session
):
    hook = _connect(client, team)
    instance = _instance(db, team.seller)
    bodies = [
        _message(instance, "G1", {"conversation": "oi grupo"}, jid="120363@g.us"),
        _message(instance, "S1", {"conversation": "status"}, jid="status@broadcast"),
        _message(instance, "R1", {"reactionMessage": {"text": "👍"}}),
    ]
    results = [client.post(hook, json=body).json()["resultado"] for body in bodies]

    assert results == ["ignorada:grupo_ou_status", "ignorada:grupo_ou_status", "ignorada:tipo"]
    assert db.scalar(select(func.count()).select_from(Conversation)) == 0
    assert contact_of({"remoteJid": "123@lid", "remoteJidAlt": CLIENT_JID}) == "+5511987651234"
    assert contact_of({"remoteJid": "123@lid"}) == "lid:123"


def test_audio_e_baixado_na_hora_e_transcrito_sem_esperar_a_pausa(
    client: TestClient,
    team: Team,
    evolution: FakeEvolution,
    db: Session,
    fake_transcriber: FakeTranscriber,
):
    hook = _connect(client, team)
    instance = _instance(db, team.seller)
    audio = {"audioMessage": {"mimetype": "audio/ogg; codecs=opus", "seconds": 4, "ptt": True}}

    client.post(hook, json=_message(instance, "AU1", audio))
    evolution.media_fails = True
    client.post(hook, json=_message(instance, "AU2", audio, at=T0 + 5))

    db.expire_all()
    first, second = db.scalars(select(Message).order_by(Message.sent_at)).all()
    assert first.media_path is not None
    assert (get_settings().data_dir / first.media_path).read_bytes() == b"OggS-audio-de-teste"
    assert evolution.media_calls[0]["key"]["id"] == "AU1"
    # O preparo (transcrição + máscara) roda logo, antes da análise com LLM.
    assert first.transcription_status is TranscriptionStatus.CONCLUIDA
    assert first.text_masked == fake_transcriber.text
    assert _conversation(db).status is ConversationStatus.AGUARDANDO
    assert second.transcription_status is TranscriptionStatus.IGNORADA  # falhou, sem derrubar


def test_mensagem_apagada_pelo_vendedor_fica_guardada_e_a_gestao_ve(
    client: TestClient, team: Team, evolution: FakeEvolution, db: Session
):
    hook = _connect(client, team)
    instance = _instance(db, team.seller)
    client.post(
        hook,
        json=_message(
            instance, "P1", {"conversation": "Contemplação garantida no 1º mês!"}, from_me=True
        ),
    )
    revoke = {"protocolMessage": {"type": "REVOKE", "key": {"id": "P1", "fromMe": True}}}

    result = client.post(hook, json=_message(instance, "P2", revoke, from_me=True)).json()

    assert result["resultado"] == "apagada"
    conversation = _conversation(db)
    detail = client.get(
        f"/api/v1/conversations/{conversation.id}", headers=team.manager_headers
    ).json()
    message = detail["messages"][0]
    assert message["revoked"] is True
    assert message["text_available"] is True
    assert any("apagou mensagem" in warning for warning in detail["warnings"])
    # O mesmo vale para o evento messages.delete.
    client.post(hook, json=_message(instance, "P3", {"conversation": "outra"}, from_me=True))
    deleted = {"event": "messages.delete", "instance": instance, "data": {"id": "P3"}}
    assert client.post(hook, json=deleted).json()["resultado"] == "apagada"


def test_edicao_guarda_o_texto_original(
    client: TestClient, team: Team, evolution: FakeEvolution, db: Session
):
    hook = _connect(client, team)
    instance = _instance(db, team.seller)
    client.post(hook, json=_message(instance, "E1", {"conversation": "Sai por 500"}, from_me=True))
    edit = {
        "protocolMessage": {
            "type": "MESSAGE_EDIT",
            "key": {"id": "E1"},
            "editedMessage": {"conversation": "Sai por 800"},
        }
    }

    client.post(hook, json=_message(instance, "E2", edit, from_me=True))

    db.expire_all()
    message = db.scalar(select(Message))
    assert message is not None
    assert message.edited is True
    assert message.text_raw == "Sai por 500\n[editada no WhatsApp para: Sai por 800]"


# ---------------------------------------------------------------- análise depois da pausa
def test_analise_roda_depois_da_pausa(
    client: TestClient, team: Team, evolution: FakeEvolution, db: Session
):
    hook = _connect(client, team)
    instance = _instance(db, team.seller)
    now = datetime.now(UTC)
    client.post(
        hook,
        json=_message(instance, "X1", {"conversation": "oi"}, at=int(now.timestamp())),
    )
    settings = get_settings()

    assert enqueue_idle_conversations(settings, now=now + timedelta(minutes=5)) == 0
    assert enqueue_idle_conversations(settings, now=now + timedelta(minutes=31)) == 1

    conversation = _conversation(db)
    assert conversation.status is ConversationStatus.ANALISADA  # fila síncrona nos testes
    assert enqueue_idle_conversations(settings, now=now + timedelta(minutes=60)) == 0


def test_conversa_que_recebe_mensagem_durante_a_analise_volta_a_aguardar(
    db: Session, make_tenant: Callable[..., Tenant], monkeypatch: pytest.MonkeyPatch
):
    tenant = make_tenant()
    conversation = Conversation(
        tenant_id=tenant.id,
        source=ImportSource.EVOLUTION,
        external_id=f"wa:{uuid.uuid4().hex}:abc",
        fingerprint="f",
        status=ConversationStatus.PENDENTE,
    )
    db.add(conversation)
    db.commit()

    def chega_mensagem(stage_db: Session, current: Conversation, _settings: object) -> None:
        # Outra sessão (o webhook) grava uma mensagem nova enquanto a análise roda.
        from radar.db.session import session_scope

        with session_scope(tenant.id) as other:
            row = other.get(Conversation, current.id)
            assert row is not None
            row.status = ConversationStatus.AGUARDANDO

    monkeypatch.setattr(processing, "STAGES", [("chega_mensagem", chega_mensagem)])
    processing.process_conversation(conversation.id, tenant.id)

    db.expire_all()
    assert db.get(Conversation, conversation.id).status is ConversationStatus.AGUARDANDO  # type: ignore[union-attr]
