"""Fila de jobs no PostgreSQL (``RADAR_QUEUE_MODE=postgres``), o modo do Docker Compose."""

from __future__ import annotations

import signal
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from radar import testing
from radar.cli import app as cli
from radar.config import get_settings
from radar.db.base import utcnow
from radar.db.models import QueuedJob
from radar.worker import pg_queue
from radar.worker.queue import enqueue


@pytest.fixture(autouse=True)
def _modo_postgres(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "queue_mode", "postgres")
    testing.JOB_CALLS.clear()
    yield
    testing.JOB_CALLS.clear()


def _job(db: Session, job_id: str) -> QueuedJob:
    db.expire_all()
    job = db.get(QueuedJob, job_id)
    assert job is not None
    return job


def _claim(now: datetime | None = None) -> pg_queue.ClaimedJob:
    claimed = pg_queue.claim_next(now)
    assert claimed is not None
    return claimed


def test_enqueue_grava_na_tabela_e_o_worker_executa(db: Session):
    job_id = enqueue(testing.record_job, "a", 1, job_id="j1", chave="valor")

    assert job_id == "j1"
    assert _job(db, "j1").status == "queued"

    assert pg_queue.PostgresWorker().run(burst=True) == 1

    assert testing.JOB_CALLS == [(("a", 1), {"chave": "valor"})]
    job = _job(db, "j1")
    assert job.status == "finished"
    assert job.attempts == 1
    assert job.finished_at is not None


def test_mesmo_job_id_nao_duplica_enquanto_ativo_e_volta_depois_de_concluido(db: Session):
    enqueue(testing.record_job, "primeiro", job_id="dup")
    enqueue(testing.record_job, "segundo", job_id="dup")

    assert db.scalar(select(func.count()).select_from(QueuedJob)) == 1
    assert _job(db, "dup").args == ["primeiro"]

    pg_queue.PostgresWorker().run(burst=True)
    enqueue(testing.record_job, "terceiro", job_id="dup")
    pg_queue.PostgresWorker().run(burst=True)

    assert [args for args, _ in testing.JOB_CALLS] == [("primeiro",), ("terceiro",)]


def test_job_com_atraso_espera_a_hora_marcada():
    enqueue(testing.record_job, job_id="depois", delay=timedelta(minutes=5))

    assert pg_queue.claim_next() is None
    assert _claim(utcnow() + timedelta(minutes=6)).id == "depois"


def test_falha_volta_para_a_fila_com_espera_e_depois_vira_failed(db: Session):
    enqueue(testing.failing_job, job_id="ruim", max_retries=1)
    worker = pg_queue.PostgresWorker()

    assert worker.execute(_claim()) is False
    job = _job(db, "ruim")
    assert job.status == "queued"
    assert job.attempts == 1
    assert "falha simulada" in job.error
    assert job.run_at > utcnow() + timedelta(seconds=20)
    assert pg_queue.claim_next() is None  # ainda esperando a próxima tentativa

    assert worker.execute(_claim(utcnow() + timedelta(minutes=1))) is False
    job = _job(db, "ruim")
    assert job.status == "failed"
    assert job.attempts == 2


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="timeout usa SIGALRM (Unix)")
def test_timeout_interrompe_o_job(db: Session):
    enqueue(testing.slow_job, 5, job_id="lento", job_timeout=1)

    assert pg_queue.PostgresWorker().execute(_claim()) is False

    job = _job(db, "lento")
    assert job.status == "failed"
    assert "JobTimeoutError" in job.error


def test_job_abandonado_volta_para_a_fila_e_o_worker_antigo_nao_sobrescreve(db: Session):
    enqueue(testing.record_job, job_id="orfao", job_timeout=60, max_retries=1)
    old = _claim()

    assert pg_queue.recover_abandoned() == 0  # ainda dentro do tempo limite
    later = utcnow() + timedelta(seconds=60) + pg_queue.STALE_GRACE + timedelta(seconds=1)
    assert pg_queue.recover_abandoned(later) == 1
    assert _job(db, "orfao").status == "queued"

    new = _claim(later)
    assert new.started_at != old.started_at
    pg_queue.PostgresWorker().execute(old)  # o worker "morto" termina atrasado

    assert _job(db, "orfao").status == "started"  # a reserva nova continua valendo


@pytest.mark.skipif(
    threading.current_thread() is not threading.main_thread(),
    reason="sinais só chegam na thread principal",
)
def test_sigterm_no_meio_do_job_devolve_o_job_para_a_fila(db: Session):
    enqueue(testing.sigterm_job, job_id="interrompido")

    handled = pg_queue.PostgresWorker().run(burst=True)

    assert handled == 0
    assert testing.JOB_CALLS == []  # interrompido antes de terminar
    job = _job(db, "interrompido")
    assert job.status == "queued"
    assert job.attempts == 0  # a interrupção não conta como tentativa


def test_limpeza_apaga_concluidos_antigos():
    enqueue(testing.record_job, job_id="velho")
    pg_queue.PostgresWorker().run(burst=True)

    assert pg_queue.purge_old() == 0
    assert pg_queue.purge_old(utcnow() + timedelta(hours=2)) == 1


def test_so_funcoes_de_modulo_vao_para_a_fila():
    with pytest.raises(ValueError, match="nível do módulo"):
        enqueue(lambda: None)


def test_cli_worker_consome_a_fila_do_postgres():
    enqueue(testing.record_job, "via-cli")

    result = CliRunner().invoke(cli, ["worker", "--burst"])

    assert result.exit_code == 0, result.output
    assert testing.JOB_CALLS == [(("via-cli",), {})]


def test_ready_confere_a_tabela_da_fila(client: TestClient):
    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "queue": "ok"}
