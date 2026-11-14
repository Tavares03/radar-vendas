"""Export no formato do WhatsApp: o parser do Radar lê de volta exatamente o que foi gerado."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from radar.ingest import open_export, parse_chat
from radar.taxonomy import MessageKind
from radar_synth.generator import generate_conversation
from radar_synth.writers import export_zip, render_export

FORMATS = [("android", "pt"), ("ios", "pt"), ("android", "en"), ("ios", "en")]


def _conversations(n: int = 12):  # type: ignore[no-untyped-def]
    sectors = ("consorcio", "seguros", "imobiliaria", "clinica", "generico")
    return [generate_conversation(seed=s, sector=sectors[s % 5]) for s in range(n)]


@pytest.mark.parametrize(("platform", "language"), FORMATS)
def test_ida_e_volta_pelo_parser(platform: str, language: str):
    for conversation in _conversations():
        files = render_export(conversation, platform=platform, language=language)
        chat = parse_chat(files.chat_text)

        assert chat.platform == platform
        parsed = chat.content_messages
        assert len(parsed) == len(conversation.messages)
        for original, read in zip(conversation.messages, parsed, strict=True):
            assert read.author == original.author
            expected_time = original.timestamp
            if platform == "android":
                expected_time = expected_time.replace(second=0)
            assert read.timestamp == expected_time
            if original.kind == "audio":
                assert read.kind is MessageKind.AUDIO
                assert read.attachment is not None
                assert files.media[f"{read.attachment}.txt"].decode() == original.text
            else:
                assert read.kind is MessageKind.TEXTO
                assert read.text == original.text


def test_sem_midia_os_audios_aparecem_como_ocultos():
    conversation = next(c for c in _conversations(40) if any(m.kind == "audio" for m in c.messages))
    files = render_export(conversation, platform="android", language="pt", with_media=False)
    assert files.media == {}
    assert "<Mídia oculta>" in files.chat_text
    chat = parse_chat(files.chat_text)
    assert len(chat.content_messages) == len(conversation.messages)


def test_zip_abre_no_radar_com_titulo_e_transcricoes(tmp_path: Path):
    conversation = next(c for c in _conversations(40) if any(m.kind == "audio" for m in c.messages))
    name, data = export_zip(conversation, platform="ios", language="pt")
    path = tmp_path / name
    path.write_bytes(data)

    with open_export(path) as bundle:
        chat = parse_chat(bundle.chat_text)
        assert bundle.title == conversation.customer_display
        audios = [m for m in chat.content_messages if m.kind is MessageKind.AUDIO]
        assert audios
        for message in audios:
            assert message.attachment is not None
            assert bundle.has_media(message.attachment)
            assert bundle.read_sidecar(message.attachment)


def test_radar_identifica_vendedor_e_cliente_nos_exports(tmp_path: Path):
    from radar.ingest import identify_participants
    from radar.taxonomy import SenderRole

    for conversation in _conversations(20):
        name, data = export_zip(conversation, platform="android", language="pt")
        path = tmp_path / name
        path.write_bytes(data)
        with open_export(path) as bundle:
            chat = parse_chat(bundle.chat_text)
            roles = identify_participants(
                chat.authors, sellers=[], chat_title=bundle.title, messages=chat.content_messages
            )
        assert roles[conversation.seller_display].role is SenderRole.VENDEDOR
        assert roles[conversation.customer_display].role is SenderRole.CLIENTE


def test_zip_e_reprodutivel(monkeypatch: pytest.MonkeyPatch):
    import time

    conversation = _conversations(1)[0]
    first = export_zip(conversation, platform="ios", language="pt")
    later = time.time() + 3600
    monkeypatch.setattr(time, "time", lambda: later)  # o relógio andou uma hora
    second = export_zip(conversation, platform="ios", language="pt")
    assert first == second


def test_nome_do_zip_segue_o_padrao_do_aplicativo():
    conversation = _conversations(1)[0]
    pt_name, _ = export_zip(conversation, platform="android", language="pt")
    en_name, _ = export_zip(conversation, platform="android", language="en")
    assert pt_name == f"Conversa do WhatsApp com {conversation.customer_display}.zip"
    assert en_name == f"WhatsApp Chat with {conversation.customer_display}.zip"
    with zipfile.ZipFile(io.BytesIO(export_zip(conversation, platform="android")[1])) as archive:
        assert f"Conversa do WhatsApp com {conversation.customer_display}.txt" in archive.namelist()
