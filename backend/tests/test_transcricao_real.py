"""Áudio de verdade, Whisper de verdade, do upload ao texto.

Lento (baixa o modelo na primeira vez). Rode com ``RADAR_RUN_SLOW_TESTS=1``.
Os áudios de ``data/samples/audio`` são fala sintética (TTS), não a voz de uma pessoa.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.models import Message
from radar.taxonomy import MessageKind, Role, TranscriptionStatus
from radar.testing import AccountFactory, make_zip
from radar.transcription import FasterWhisperTranscriber, set_transcriber

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples" / "audio"


@pytest.fixture
def real_whisper() -> Iterator[None]:
    set_transcriber(FasterWhisperTranscriber("base", device="cpu", compute_type="int8"))
    yield
    set_transcriber(None, clear=True)


@pytest.mark.slow
def test_export_com_opus_e_transcrito_de_ponta_a_ponta(
    client: TestClient, make_account: AccountFactory, db: Session, real_whisper: None
):
    admin = make_account(Role.ADMIN)
    chat = (
        "[10/01/2024, 09:00:00] Carla Mendes: Bom dia! Em que posso ajudar?\n"
        "[10/01/2024, 09:01:00] Roberto Lima: ‎<anexado: 00000002-AUDIO-2024-01-10-09-01-00.opus>\n"
        "[10/01/2024, 09:03:00] Carla Mendes: ‎<anexado: 00000003-AUDIO-2024-01-10-09-03-00.opus>\n"
    )
    archive = make_zip(
        {
            "_chat.txt": chat,
            "00000002-AUDIO-2024-01-10-09-01-00.opus": (
                SAMPLES / "cliente-pede-simulacao.opus"
            ).read_bytes(),
            "00000003-AUDIO-2024-01-10-09-03-00.opus": (
                SAMPLES / "vendedor-promete-contemplacao.opus"
            ).read_bytes(),
        }
    )

    response = client.post(
        "/api/v1/imports",
        headers=admin.headers,
        files=[("files", ("WhatsApp Chat - Roberto Lima.zip", archive))],
    )

    assert response.status_code == 201, response.text
    assert response.json()[0]["status"] == "concluido"
    audios = db.scalars(
        select(Message).where(Message.kind == MessageKind.AUDIO).order_by(Message.position)
    ).all()
    assert [a.transcription_status for a in audios] == [TranscriptionStatus.CONCLUIDA] * 2
    customer, seller = (a.text_raw.lower() for a in audios)
    assert "consórcio" in customer
    assert "simulação" in customer
    assert "contemplado" in seller
    assert "garanto" in seller
    assert all(a.media_seconds and a.media_seconds > 3 for a in audios)
    assert all(a.transcription_model == "faster-whisper-base" for a in audios)
