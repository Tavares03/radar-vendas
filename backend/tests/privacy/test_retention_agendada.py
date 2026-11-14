"""Retenção pelo agendador e pela CLI."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from radar.cli import app as cli
from radar.db.models import Message
from radar.taxonomy import Role
from radar.testing import AccountFactory
from radar.worker.runner import PERIODIC

CHAT = "10/01/2024 09:00 - Roberto Lima: Meu CPF é 529.982.247-25\n"


def _old_conversation(client: TestClient, db: Session, headers: dict[str, str]) -> uuid.UUID:
    response = client.post(
        "/api/v1/imports",
        headers=headers,
        files=[("files", ("Conversa do WhatsApp com Roberto Lima.txt", CHAT.encode()))],
    )
    conversation_id = uuid.UUID(response.json()[0]["conversation_id"])
    db.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id)
        .values(created_at=datetime.now(UTC) - timedelta(days=365))
    )
    db.commit()
    return conversation_id


def _raw(db: Session, conversation_id: uuid.UUID) -> str | None:
    db.expire_all()
    return db.scalars(
        select(Message.text_raw).where(Message.conversation_id == conversation_id)
    ).one()


def test_retencao_e_tarefa_periodica_do_agendador(
    client: TestClient, make_account: AccountFactory, db: Session
):
    import radar.worker.jobs  # noqa: F401  (registra as tarefas)

    tasks = {name: (every, func) for name, every, func in PERIODIC}
    assert "retencao" in tasks
    every, func = tasks["retencao"]
    assert every <= timedelta(hours=24)

    admin = make_account(Role.ADMIN)
    conversation_id = _old_conversation(client, db, admin.headers)
    func()

    assert _raw(db, conversation_id) is None


def test_cli_simula_e_aplica_a_retencao(
    client: TestClient, make_account: AccountFactory, db: Session
):
    admin = make_account(Role.ADMIN)
    conversation_id = _old_conversation(client, db, admin.headers)
    runner = CliRunner()

    simulated = runner.invoke(cli, ["retention-run", "--dry-run"])
    assert simulated.exit_code == 0, simulated.output
    assert "Simulação" in simulated.output
    assert "1 mensagem" in simulated.output
    assert _raw(db, conversation_id) is not None

    applied = runner.invoke(cli, ["retention-run"])
    assert applied.exit_code == 0, applied.output
    assert _raw(db, conversation_id) is None
