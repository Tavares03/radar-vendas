"""Etapa de privacidade do pipeline: máscara das mensagens e índice de titulares."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.models import Conversation, Message, PiiIndexEntry, Tenant
from radar.privacy.crypto import subject_hash
from radar.services.processing import process_conversation
from radar.taxonomy import Role
from radar.testing import AccountFactory, FakeTranscriber, make_zip

CHAT_NAME = "Conversa do WhatsApp com Roberto Lima.txt"
CPF = "529.982.247-25"
CHAT = (
    "10/01/2024 09:00 - Roberto Lima: Oi, quanto custa o consórcio?\n"
    "10/01/2024 09:02 - Carla Mendes: Bom dia, Roberto! Meu e-mail é carla@exemplo.com\n"
    f"10/01/2024 09:05 - Roberto Lima: Meu CPF é {CPF}, cel (11) 91234-5678\n"
)


def _import(client: TestClient, headers: dict[str, str], content: bytes, name: str = CHAT_NAME):
    response = client.post("/api/v1/imports", headers=headers, files=[("files", (name, content))])
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()[0]["conversation_id"])


def _messages(db: Session, conversation_id: uuid.UUID) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.position)
        )
    )


def test_mensagens_ficam_mascaradas_apos_a_importacao(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())

    first, second, third = _messages(db, conversation_id)

    assert first.text_masked == "Oi, quanto custa o consórcio?"
    assert first.pii_spans == []
    # O nome do cliente vem da lista de participantes do export.
    assert second.text_masked == "Bom dia, [NOME_PESSOA]! Meu e-mail é [EMAIL]"
    assert third.text_masked == "Meu CPF é [CPF], cel [TELEFONE]"
    assert third.pii_spans == [
        {"type": "CPF", "start": 10, "end": 15},
        {"type": "TELEFONE", "start": 21, "end": 31},
    ]
    # O original continua guardado (cifrado) para quem pode revelar.
    assert third.text_raw == f"Meu CPF é {CPF}, cel (11) 91234-5678"


def test_api_mostra_o_texto_mascarado_com_os_destaques(
    client: TestClient, make_account: AccountFactory
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())

    body = client.get(f"/api/v1/conversations/{conversation_id}", headers=admin.headers).json()

    third = body["messages"][2]
    assert third["text_available"] is True
    assert third["revealed"] is False
    assert third["text"] == "Meu CPF é [CPF], cel [TELEFONE]"
    assert third["pii_spans"][0] == {"type": "CPF", "start": 10, "end": 15}
    dump = str(body)
    assert CPF not in dump
    assert "91234-5678" not in dump
    assert "Roberto" not in dump


def test_indice_de_titulares_guarda_so_o_hmac(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    tenant_id = admin.tenant.id
    conversation_id = _import(client, admin.headers, CHAT.encode())

    entries = db.scalars(
        select(PiiIndexEntry).where(PiiIndexEntry.conversation_id == conversation_id)
    ).all()
    by_hash = {(e.subject_hash, e.pii_type) for e in entries}

    assert (subject_hash(tenant_id, CPF), "CPF") in by_hash
    assert (subject_hash(tenant_id, "11912345678"), "TELEFONE") in by_hash
    assert (subject_hash(tenant_id, "carla@exemplo.com"), "EMAIL") in by_hash
    # O próprio cliente (participante) também é localizável.
    assert (subject_hash(tenant_id, "Roberto Lima"), "PARTICIPANTE") in by_hash
    stored = " ".join(f"{e.subject_hash} {e.pii_type}" for e in entries)
    assert CPF not in stored
    assert "52998224725" not in stored


def test_reprocessar_nao_duplica_o_indice(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())
    count = len(db.scalars(select(PiiIndexEntry)).all())

    for message in _messages(db, conversation_id):
        message.text_masked = None  # força mascarar tudo de novo
    db.commit()
    process_conversation(conversation_id, admin.tenant.id)
    process_conversation(conversation_id, admin.tenant.id)

    db.expire_all()
    assert len(db.scalars(select(PiiIndexEntry)).all()) == count
    assert _messages(db, conversation_id)[2].text_masked == "Meu CPF é [CPF], cel [TELEFONE]"


def test_empresa_pode_desligar_a_mascara_de_nomes(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    tenant = db.get(Tenant, admin.tenant.id)
    assert tenant is not None
    settings = tenant.get_settings()
    settings.mask_person_names = False
    tenant.set_settings(settings)
    db.commit()

    conversation_id = _import(client, admin.headers, CHAT.encode())

    second = _messages(db, conversation_id)[1]
    assert second.text_masked == "Bom dia, Roberto! Meu e-mail é [EMAIL]"


def test_audio_transcrito_tambem_e_mascarado(
    client: TestClient,
    make_account: AccountFactory,
    db: Session,
    fake_transcriber: FakeTranscriber,
):
    fake_transcriber.text = f"anota aí meu cpf {CPF}"
    admin = make_account(Role.ADMIN)
    chat = (
        "10/01/2024 09:00 - Carla Mendes: Bom dia!\n"
        "10/01/2024 09:01 - Roberto Lima: PTT-20240110-WA0001.opus (arquivo anexado)\n"
    )
    archive = make_zip({CHAT_NAME: chat, "PTT-20240110-WA0001.opus": b"OggS"})

    conversation_id = _import(client, admin.headers, archive, name="export.zip")

    audio = _messages(db, conversation_id)[1]
    assert audio.text_raw == f"anota aí meu cpf {CPF}"
    assert audio.text_masked == "anota aí meu cpf [CPF]"


def test_mensagem_sem_texto_vira_texto_vazio_mascarado(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    chat = (
        "10/01/2024 09:00 - Carla Mendes: Bom dia!\n"
        "10/01/2024 09:01 - Roberto Lima: <Mídia oculta>\n"
    )
    conversation_id = _import(client, admin.headers, chat.encode())

    media = _messages(db, conversation_id)[1]
    assert media.text_masked == ""
    conversation = db.get(Conversation, conversation_id)
    assert conversation is not None
    assert conversation.status.value == "analisada"
