"""Política de retenção: texto bruto, áudios e conversas inteiras."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from radar.config import get_settings, reset_settings_cache
from radar.db.models import AuditLog, Conversation, Message, PiiIndexEntry, Tenant
from radar.services.accounts import create_tenant
from radar.services.retention import run_retention, run_retention_all
from radar.taxonomy import Role
from radar.testing import AccountFactory, FakeTranscriber, make_zip

CHAT_NAME = "Conversa do WhatsApp com Roberto Lima.txt"
CHAT = (
    "10/01/2024 09:00 - Roberto Lima: Oi, quanto custa?\n"
    "10/01/2024 09:05 - Roberto Lima: Meu CPF é 529.982.247-25\n"
)
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _import(client: TestClient, headers: dict[str, str], content: bytes, name: str = CHAT_NAME):
    response = client.post("/api/v1/imports", headers=headers, files=[("files", (name, content))])
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()[0]["conversation_id"])


def _age(db: Session, conversation_id: uuid.UUID, days: int) -> None:
    """Finge que a conversa chegou há ``days`` dias."""
    when = NOW - timedelta(days=days)
    db.execute(
        update(Message).where(Message.conversation_id == conversation_id).values(created_at=when)
    )
    db.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(created_at=when)
    )
    db.commit()


def _set_policy(db: Session, tenant_id: uuid.UUID, **values: int) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    settings = tenant.get_settings()
    for key, value in values.items():
        setattr(settings, key, value)
    tenant.set_settings(settings)
    db.commit()
    return tenant


def _messages(db: Session, conversation_id: uuid.UUID) -> list[Message]:
    db.expire_all()
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.position)
        )
    )


def test_empresa_nova_herda_os_prazos_padrao_da_instalacao(
    db: Session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("RADAR_DEFAULT_RETENTION_RAW_DAYS", "15")
    monkeypatch.setenv("RADAR_DEFAULT_RETENTION_MEDIA_DAYS", "7")
    reset_settings_cache()
    try:
        tenant = create_tenant(db, "Empresa Prazo Curto")
    finally:
        monkeypatch.undo()
        reset_settings_cache()

    policy = tenant.get_settings()
    assert (policy.retention_raw_days, policy.retention_media_days) == (15, 7)


def test_texto_bruto_antigo_e_apagado_e_a_mascara_fica(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    old = _import(client, admin.headers, CHAT.encode())
    recent = _import(
        client,
        admin.headers,
        b"11/01/2024 10:00 - Ana Souza: Oi, tem plano de 50 mil?\n",
        name="Conversa do WhatsApp com Ana Souza.txt",
    )
    _age(db, old, 91)
    _age(db, recent, 89)
    tenant = _set_policy(db, admin.tenant.id, retention_raw_days=90)

    report = run_retention(db, tenant, get_settings(), now=NOW)
    db.commit()

    assert report.raw_messages_purged == 2
    purged = _messages(db, old)
    assert all(m.text_raw is None for m in purged)
    assert purged[1].text_masked == "Meu CPF é [CPF]"
    assert db.get(Conversation, old).raw_purged_at == NOW  # type: ignore[union-attr]
    kept = _messages(db, recent)
    assert kept[0].text_raw == "Oi, tem plano de 50 mil?"
    assert db.get(Conversation, recent).raw_purged_at is None  # type: ignore[union-attr]


def test_mensagem_ainda_sem_mascara_e_mascarada_antes_de_perder_o_original(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())
    db.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id)
        .values(text_masked=None, pii_spans=[])
    )
    db.execute(delete(PiiIndexEntry).where(PiiIndexEntry.conversation_id == conversation_id))
    db.commit()
    _age(db, conversation_id, 200)
    tenant = _set_policy(db, admin.tenant.id, retention_raw_days=90)

    report = run_retention(db, tenant, get_settings(), now=NOW)
    db.commit()

    assert report.masked_before_purge == 2
    second = _messages(db, conversation_id)[1]
    assert second.text_raw is None
    assert second.text_masked == "Meu CPF é [CPF]"
    # O índice de titulares continua achando a conversa pelo CPF.
    assert db.scalars(
        select(PiiIndexEntry).where(
            PiiIndexEntry.conversation_id == conversation_id, PiiIndexEntry.pii_type == "CPF"
        )
    ).first()


def test_zero_dias_significa_nunca_apagar(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())
    _age(db, conversation_id, 5000)
    tenant = _set_policy(db, admin.tenant.id, retention_raw_days=0, retention_media_days=0)

    report = run_retention(db, tenant, get_settings(), now=NOW)

    assert report.raw_messages_purged == 0
    assert _messages(db, conversation_id)[1].text_raw is not None


def test_audio_antigo_e_apagado_do_disco(
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
    archive = make_zip({CHAT_NAME: chat, "PTT-20240110-WA0001.opus": b"OggS"})
    conversation_id = _import(client, admin.headers, archive, name="export.zip")
    audio = _messages(db, conversation_id)[1]
    assert audio.media_path is not None
    path = get_settings().data_dir / audio.media_path
    assert path.is_file()
    _age(db, conversation_id, 31)
    tenant = _set_policy(db, admin.tenant.id, retention_media_days=30, retention_raw_days=0)

    report = run_retention(db, tenant, get_settings(), now=NOW)
    db.commit()

    assert report.media_files_deleted == 1
    assert not path.exists()
    audio = _messages(db, conversation_id)[1]
    assert audio.media_path is None
    # A transcrição (texto) segue a política do texto, não a do áudio.
    assert audio.text_raw == fake_transcriber.text
    assert db.get(Conversation, conversation_id).media_purged_at == NOW  # type: ignore[union-attr]


def test_conversa_inteira_some_quando_a_empresa_define_prazo(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    old = _import(client, admin.headers, CHAT.encode())
    _age(db, old, 400)
    tenant = _set_policy(db, admin.tenant.id, retention_conversation_days=365)

    report = run_retention(db, tenant, get_settings(), now=NOW)
    db.commit()

    assert report.conversations_deleted == 1
    db.expire_all()
    assert db.get(Conversation, old) is None
    assert db.scalars(select(PiiIndexEntry).where(PiiIndexEntry.conversation_id == old)).all() == []


def test_conversa_antiga_com_mensagem_nova_nao_e_apagada(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())
    _age(db, conversation_id, 400)
    # Um export mais novo da mesma conversa chega hoje.
    newer = CHAT + "12/01/2024 08:00 - Roberto Lima: E aí, conseguiu a simulação?\n"
    assert _import(client, admin.headers, newer.encode()) == conversation_id
    db.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id, Message.position == 2)
        .values(created_at=NOW - timedelta(days=1))
    )
    db.commit()
    tenant = _set_policy(db, admin.tenant.id, retention_conversation_days=365)

    report = run_retention(db, tenant, get_settings(), now=NOW)

    assert report.conversations_deleted == 0
    assert db.get(Conversation, conversation_id) is not None


def test_simulacao_nao_altera_nada(client: TestClient, make_account: AccountFactory, db: Session):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())
    _age(db, conversation_id, 400)
    tenant = _set_policy(
        db, admin.tenant.id, retention_raw_days=90, retention_conversation_days=365
    )

    report = run_retention(db, tenant, get_settings(), now=NOW, dry_run=True)
    db.commit()

    assert report.dry_run is True
    assert report.raw_messages_purged == 2
    assert report.conversations_deleted == 1
    assert _messages(db, conversation_id)[1].text_raw is not None


def test_retencao_de_uma_empresa_nao_toca_na_outra(
    client: TestClient, make_account: AccountFactory, db: Session
):
    first = make_account(Role.ADMIN)
    second = make_account(Role.ADMIN)
    mine = _import(client, first.headers, CHAT.encode())
    theirs = _import(client, second.headers, CHAT.encode())
    _age(db, mine, 200)
    _age(db, theirs, 200)
    _set_policy(db, second.tenant.id, retention_raw_days=0)
    _set_policy(db, first.tenant.id, retention_raw_days=90)

    reports = run_retention_all(get_settings(), now=NOW)

    assert {r.tenant_id: r.raw_messages_purged for r in reports} == {
        first.tenant.id: 2,
        second.tenant.id: 0,
    }
    assert _messages(db, theirs)[1].text_raw is not None
    actions = db.scalars(select(AuditLog.action).where(AuditLog.tenant_id == first.tenant.id)).all()
    assert "privacy.retention_run" in actions
    # Empresa sem nada apagado não ganha registro de auditoria a cada execução agendada.
    assert (
        "privacy.retention_run"
        not in db.scalars(
            select(AuditLog.action).where(AuditLog.tenant_id == second.tenant.id)
        ).all()
    )


def test_revelar_depois_da_retencao_mostra_so_a_mascara(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _import(client, admin.headers, CHAT.encode())
    _age(db, conversation_id, 200)
    run_retention_all(get_settings(), now=NOW)

    body = client.get(
        f"/api/v1/conversations/{conversation_id}?reveal=true", headers=admin.headers
    ).json()

    assert body["raw_purged"] is True
    assert body["messages"][1]["text"] == "Meu CPF é [CPF]"
    assert body["messages"][1]["revealed"] is False
