"""Envio de exports: do arquivo à conversa gravada."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from radar.config import get_settings
from radar.db.models import AuditLog, Conversation, Import, Message, Seller, Tenant
from radar.taxonomy import (
    ConversationStatus,
    MessageKind,
    Role,
    SenderRole,
    TranscriptionStatus,
)
from radar.testing import AccountFactory, FakeTranscriber, make_zip

CHAT = (
    "10/01/2024 09:00 - As mensagens e ligações são protegidas com a criptografia de ponta a ponta.\n"
    "10/01/2024 09:00 - Roberto Lima: Oi, vi o anúncio do consórcio. Quanto custa?\n"
    "10/01/2024 09:02 - Carla Mendes: Bom dia, Roberto! Aqui é a Carla. Posso te ajudar\n"
    "10/01/2024 09:03 - Carla Mendes: Temos planos a partir de R$ 800 por mês\n"
    "10/01/2024 09:05 - Roberto Lima: Meu CPF é 529.982.247-25, pode simular?\n"
)
CHAT_NAME = "Conversa do WhatsApp com Roberto Lima.txt"
URL = "/api/v1/imports"


def _upload(client: TestClient, headers: dict[str, str], *files: tuple[str, bytes | str], **data):
    payload = [
        ("files", (name, content.encode() if isinstance(content, str) else content))
        for name, content in files
    ]
    return client.post(URL, headers=headers, files=payload, data=data)


def test_upload_de_txt_cria_conversa_e_mensagens(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)

    response = _upload(client, admin.headers, (CHAT_NAME, CHAT))

    assert response.status_code == 201, response.text
    (item,) = response.json()
    assert item["status"] == "concluido"
    assert item["filename"] == CHAT_NAME
    assert item["duplicate"] is False
    assert item["stats"]["mensagens_novas"] == 4
    assert item["stats"]["mensagens_de_sistema"] == 1
    assert item["stats"]["formato"] == "android"

    conversation = db.scalars(select(Conversation)).one()
    assert str(conversation.id) == item["conversation_id"]
    assert conversation.tenant_id == admin.tenant.id
    assert conversation.message_count == 4
    assert conversation.seller_message_count == 2
    assert conversation.customer_message_count == 2
    assert conversation.status is ConversationStatus.ANALISADA
    # 09:00 em São Paulo (UTC-3) é 12:00 UTC.
    assert conversation.started_at == datetime(2024, 1, 10, 12, 0, tzinfo=UTC)
    assert conversation.last_message_at == datetime(2024, 1, 10, 12, 5, tzinfo=UTC)

    # O título do export identifica o cliente; o vendedor é cadastrado na hora.
    seller = db.scalars(select(Seller)).one()
    assert seller.display_name == "Carla Mendes"
    assert conversation.seller_id == seller.id
    assert conversation.customer_name == "Roberto Lima"
    assert conversation.customer_label.startswith("Cliente ")
    assert "Roberto" not in conversation.customer_label

    messages = db.scalars(select(Message).order_by(Message.position)).all()
    assert [m.sender_role for m in messages] == [
        SenderRole.CLIENTE,
        SenderRole.VENDEDOR,
        SenderRole.VENDEDOR,
        SenderRole.CLIENTE,
    ]
    assert messages[3].text_raw == "Meu CPF é 529.982.247-25, pode simular?"

    assert db.scalars(select(AuditLog).where(AuditLog.action == "import.created")).one()


def test_texto_bruto_fica_cifrado_no_banco(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    _upload(client, admin.headers, (CHAT_NAME, CHAT))

    # SQL cru: é o que alguém com acesso direto ao banco (ou a um dump) enxergaria.
    stored = db.execute(text("SELECT text_raw FROM messages")).scalars().all()
    assert len(stored) == 4
    assert all(value.startswith("enc:v1:") for value in stored)
    assert not any("529.982" in value for value in stored)
    names = [
        *db.execute(text("SELECT customer_name FROM conversations")).scalars(),
        *db.execute(text("SELECT filename FROM imports")).scalars(),
        *db.execute(text("SELECT CAST(participants AS TEXT) FROM conversations")).scalars(),
    ]
    assert len(names) == 3
    assert all("Roberto" not in value for value in names)


def test_upload_some_do_disco_depois_de_processado(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    _upload(client, admin.headers, (CHAT_NAME, CHAT))

    folder = get_settings().uploads_dir / str(admin.tenant.id)
    assert not folder.exists() or list(folder.iterdir()) == []
    assert db.scalars(select(Import)).one().stored_path is None


def test_mesmo_arquivo_de_novo_nao_duplica(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    first = _upload(client, admin.headers, (CHAT_NAME, CHAT)).json()[0]

    second = _upload(client, admin.headers, ("outro nome.txt", CHAT)).json()[0]

    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(db.scalars(select(Conversation)).all()) == 1
    assert len(db.scalars(select(Message)).all()) == 4


def test_export_mais_novo_da_mesma_conversa_so_acrescenta(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    _upload(client, admin.headers, (CHAT_NAME, CHAT))
    newer = CHAT + (
        "11/01/2024 10:00 - Carla Mendes: Roberto, segue a simulação\n"
        "11/01/2024 10:05 - Roberto Lima: Obrigado, vou pensar\n"
    )

    item = _upload(client, admin.headers, (CHAT_NAME, newer)).json()[0]

    assert item["duplicate"] is False
    assert item["stats"]["mensagens_novas"] == 2
    assert item["stats"]["mensagens_repetidas"] == 4
    assert item["stats"]["conversa_nova"] is False
    conversation = db.scalars(select(Conversation)).one()
    assert conversation.message_count == 6
    positions = db.scalars(select(Message.position).order_by(Message.position)).all()
    assert positions == [0, 1, 2, 3, 4, 5]


def test_mensagens_identicas_no_mesmo_minuto_sao_mantidas(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    chat = (
        "10/01/2024 09:00 - Roberto Lima: ok\n"
        "10/01/2024 09:00 - Roberto Lima: ok\n"
        "10/01/2024 09:00 - Carla Mendes: Posso te ajudar?\n"
    )
    _upload(client, admin.headers, (CHAT_NAME, chat))
    assert db.scalars(select(Conversation)).one().message_count == 3

    # E reimportar continua sem duplicar.
    _upload(client, admin.headers, (CHAT_NAME, chat + "10/01/2024 09:09 - Roberto Lima: oi\n"))
    assert db.scalars(select(Conversation)).one().message_count == 4


def test_clientes_homonimos_nao_sao_fundidos(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    _upload(client, admin.headers, (CHAT_NAME, CHAT))
    other = (
        "05/03/2024 15:00 - Roberto Lima: Boa tarde, queria um seguro de carro\n"
        "05/03/2024 15:02 - Carla Mendes: Claro! Qual o modelo?\n"
    )

    _upload(client, admin.headers, (CHAT_NAME, other))

    conversations = db.scalars(select(Conversation)).all()
    assert len(conversations) == 2
    assert sorted(c.message_count for c in conversations) == [2, 4]


def test_arquivo_invalido_nao_derruba_o_lote(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)

    response = _upload(
        client,
        admin.headers,
        ("notas.txt", "isto não é uma conversa exportada"),
        (CHAT_NAME, CHAT),
        ("foto.png", b"\x89PNG"),
        ("armadilha.zip", make_zip({"_chat.txt": CHAT, "../../fora.txt": b"x"})),
    )

    assert response.status_code == 201
    bad, good, wrong_type, trap = response.json()
    assert bad["status"] == "falhou"
    assert "Exportar conversa" in bad["error"]
    assert good["status"] == "concluido"
    assert wrong_type["status"] == "falhou"
    assert "Tipo de arquivo" in wrong_type["error"]
    assert trap["status"] == "falhou"
    assert "inválido" in trap["error"]
    assert len(db.scalars(select(Conversation)).all()) == 1


def test_zip_com_audio_e_transcrito(
    client: TestClient,
    make_account: AccountFactory,
    db: Session,
    fake_transcriber: FakeTranscriber,
):
    fake_transcriber.text = "quero fechar o consórcio ainda esta semana"
    admin = make_account(Role.ADMIN)
    chat = (
        "[10/01/2024, 09:00:00] Carla Mendes: Bom dia! Em que posso ajudar?\n"
        "[10/01/2024, 09:01:00] Roberto Lima: ‎<anexado: 00000002-AUDIO-2024-01-10-09-01-00.opus>\n"
        "[10/01/2024, 09:02:00] Roberto Lima: ‎<anexado: 00000003-AUDIO-sem-arquivo.opus>\n"
        "[10/01/2024, 09:03:00] Roberto Lima: ‎<anexado: 00000004-PHOTO-2024-01-10.jpg>\n"
    )
    archive = make_zip(
        {
            "_chat.txt": chat,
            "00000002-AUDIO-2024-01-10-09-01-00.opus": b"OggS-audio-falso",
            "00000004-PHOTO-2024-01-10.jpg": b"\xff\xd8jpeg",
        }
    )

    item = _upload(client, admin.headers, ("WhatsApp Chat - Roberto Lima.zip", archive)).json()[0]

    assert item["status"] == "concluido", item
    assert item["stats"]["audios_para_transcrever"] == 1
    assert item["stats"]["audios_sem_arquivo"] == 1
    messages = db.scalars(select(Message).order_by(Message.position)).all()
    audio, missing, photo = messages[1], messages[2], messages[3]
    assert audio.kind is MessageKind.AUDIO
    assert audio.transcription_status is TranscriptionStatus.CONCLUIDA
    assert audio.text_raw == "quero fechar o consórcio ainda esta semana"
    assert audio.transcription_model == "fake"
    assert audio.media_seconds == 4.2
    assert audio.media_path
    assert audio.media_path.startswith(f"media/{admin.tenant.id}/")
    assert (get_settings().data_dir / audio.media_path).read_bytes() == b"OggS-audio-falso"
    assert len(fake_transcriber.calls) == 1

    assert missing.transcription_status is TranscriptionStatus.IGNORADA
    assert missing.media_path is None
    # Só áudio vai para o disco: a foto fica de fora (minimização).
    assert photo.kind is MessageKind.IMAGEM
    assert photo.media_path is None
    conversation = db.scalars(select(Conversation)).one()
    assert conversation.audio_count == 2
    assert any("Incluir mídia" in warning for warning in conversation.warnings)


def test_audio_com_transcricao_desligada_fica_marcado(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    chat = (
        "10/01/2024 09:00 - Carla Mendes: Bom dia!\n"
        "10/01/2024 09:01 - Roberto Lima: PTT-20240110-WA0001.opus (arquivo anexado)\n"
    )
    archive = make_zip({CHAT_NAME: chat, "PTT-20240110-WA0001.opus": b"OggS"})

    item = _upload(client, admin.headers, ("export.zip", archive)).json()[0]

    assert item["status"] == "concluido"
    audio = db.scalars(select(Message).where(Message.kind == MessageKind.AUDIO)).one()
    assert audio.transcription_status is TranscriptionStatus.IGNORADA
    assert db.scalars(select(Conversation)).one().status is ConversationStatus.ANALISADA


def test_falha_na_transcricao_nao_derruba_a_conversa(
    client: TestClient,
    make_account: AccountFactory,
    db: Session,
    fake_transcriber: FakeTranscriber,
):
    fake_transcriber.fail = True
    admin = make_account(Role.ADMIN)
    chat = (
        "10/01/2024 09:00 - Carla Mendes: Bom dia!\n"
        "10/01/2024 09:01 - Roberto Lima: PTT-20240110-WA0001.opus (arquivo anexado)\n"
    )
    archive = make_zip({CHAT_NAME: chat, "PTT-20240110-WA0001.opus": b"OggS"})

    _upload(client, admin.headers, ("export.zip", archive))

    audio = db.scalars(select(Message).where(Message.kind == MessageKind.AUDIO)).one()
    assert audio.transcription_status is TranscriptionStatus.FALHOU
    assert db.scalars(select(Conversation)).one().status is ConversationStatus.ANALISADA


def test_transcricao_que_acompanha_o_audio_dispensa_o_whisper(
    client: TestClient,
    make_account: AccountFactory,
    db: Session,
    fake_transcriber: FakeTranscriber,
):
    admin = make_account(Role.ADMIN)
    chat = (
        "10/01/2024 09:00 - Carla Mendes: Bom dia!\n"
        "10/01/2024 09:01 - Roberto Lima: PTT-20240110-WA0001.opus (arquivo anexado)\n"
    )
    archive = make_zip(
        {
            CHAT_NAME: chat,
            "PTT-20240110-WA0001.opus": b"OggS",
            "PTT-20240110-WA0001.opus.txt": "tenho interesse na carta de 200 mil",
        }
    )

    _upload(client, admin.headers, ("export.zip", archive))

    audio = db.scalars(select(Message).where(Message.kind == MessageKind.AUDIO)).one()
    assert audio.text_raw == "tenho interesse na carta de 200 mil"
    assert audio.transcription_status is TranscriptionStatus.CONCLUIDA
    assert audio.transcription_model == "origem"
    assert fake_transcriber.calls == []


def test_vendedor_cadastrado_e_reconhecido_pelo_apelido(
    client: TestClient,
    make_account: AccountFactory,
    make_seller: Callable[..., Seller],
    db: Session,
):
    admin = make_account(Role.ADMIN)
    seller = make_seller(admin.tenant, "Carla M.", aliases=["Carla Mendes"])

    _upload(client, admin.headers, ("_chat.txt", CHAT))

    conversation = db.scalars(select(Conversation)).one()
    assert conversation.seller_id == seller.id
    assert conversation.role_confidence == "alta"
    assert len(db.scalars(select(Seller)).all()) == 1


def test_identificacao_incerta_fica_sinalizada(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    chat = "10/01/2024 09:00 - A: oi\n10/01/2024 09:01 - B: olá\n"

    _upload(client, admin.headers, ("_chat.txt", chat))

    assert db.scalars(select(Conversation)).one().role_confidence == "baixa"


def test_vendedor_importa_so_para_si(
    client: TestClient,
    make_account: AccountFactory,
    make_tenant: Callable[..., Tenant],
    make_seller: Callable[..., Seller],
    db: Session,
):
    tenant = make_tenant()
    me = make_seller(tenant, "Diego Ramos")
    other = make_seller(tenant, "Carla Mendes")
    seller_account = make_account(Role.VENDEDOR, tenant=tenant, seller=me)

    item = _upload(
        client, seller_account.headers, (CHAT_NAME, CHAT), seller_id=str(other.id)
    ).json()[0]

    assert item["status"] == "concluido"
    conversation = db.scalars(select(Conversation)).one()
    # Mesmo pedindo outro vendedor, a conversa fica com quem enviou.
    assert conversation.seller_id == me.id


def test_vendedor_sem_vinculo_nao_importa(client: TestClient, make_account: AccountFactory):
    account = make_account(Role.VENDEDOR)
    response = _upload(client, account.headers, (CHAT_NAME, CHAT))
    assert response.status_code == 403


def test_auditor_nao_importa(client: TestClient, make_account: AccountFactory):
    auditor = make_account(Role.AUDITOR)
    response = _upload(client, auditor.headers, (CHAT_NAME, CHAT))
    assert response.status_code == 403


def test_token_de_api_precisa_do_escopo_de_ingestao(
    client: TestClient, make_account: AccountFactory
):
    admin = make_account(Role.ADMIN)

    def token(scopes: list[str]) -> dict[str, str]:
        created = client.post(
            "/api/v1/api-tokens", headers=admin.headers, json={"name": "crm", "scopes": scopes}
        )
        assert created.status_code == 201, created.text
        return {"Authorization": f"Bearer {created.json()['token']}"}

    assert _upload(client, token(["read"]), (CHAT_NAME, CHAT)).status_code == 403
    response = _upload(client, token(["ingest"]), (CHAT_NAME, CHAT))
    assert response.status_code == 201
    assert response.json()[0]["status"] == "concluido"


def test_importacoes_nao_cruzam_empresas(client: TestClient, make_account: AccountFactory):
    one, two = make_account(Role.ADMIN), make_account(Role.ADMIN)
    item = _upload(client, one.headers, (CHAT_NAME, CHAT)).json()[0]

    assert client.get(f"{URL}/{item['id']}", headers=one.headers).status_code == 200
    assert client.get(f"{URL}/{item['id']}", headers=two.headers).status_code == 404
    assert client.get(URL, headers=two.headers).json()["total"] == 0
    listing = client.get(URL, headers=one.headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["filename"] == CHAT_NAME

    # O mesmo arquivo em outra empresa é uma importação nova, não uma duplicata.
    again = _upload(client, two.headers, (CHAT_NAME, CHAT)).json()[0]
    assert again["duplicate"] is False
    assert again["id"] != item["id"]


def test_sem_arquivo_e_erro_de_validacao(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    assert client.post(URL, headers=admin.headers).status_code == 422


def test_vendedor_inexistente_responde_404(client: TestClient, make_account: AccountFactory):
    admin = make_account(Role.ADMIN)
    response = _upload(
        client,
        admin.headers,
        (CHAT_NAME, CHAT),
        seller_id="00000000-0000-4000-8000-000000000000",
    )
    assert response.status_code == 404
