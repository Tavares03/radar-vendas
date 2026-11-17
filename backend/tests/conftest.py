"""Fixtures compartilhadas pelos testes do backend.

Por padrão os testes usam SQLite em memória e fila síncrona: ``pytest`` roda sem nenhum serviço.
Defina ``RADAR_TEST_DATABASE_URL`` para rodar a mesma suíte contra PostgreSQL + pgvector (a CI faz
isso).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

# O ambiente precisa estar definido antes de qualquer import que leia a configuração.
_TMP = Path(tempfile.mkdtemp(prefix="radar-tests-"))
os.environ["RADAR_DISABLE_ENV_FILE"] = "1"
os.environ["RADAR_ENVIRONMENT"] = "test"
os.environ["RADAR_SECRET_KEY"] = "segredo-de-teste-com-mais-de-32-caracteres-ok"
os.environ["RADAR_DATABASE_URL"] = os.environ.get("RADAR_TEST_DATABASE_URL", "sqlite://")
os.environ["RADAR_QUEUE_MODE"] = "sync"
os.environ["RADAR_DATA_DIR"] = str(_TMP / "data")
os.environ["RADAR_MODELS_DIR"] = str(_TMP / "models")
os.environ["RADAR_LLM_MODE"] = "off"
os.environ["RADAR_NER_MODEL"] = "off"
os.environ["RADAR_CLASSIFIER_MODEL"] = "off"
os.environ["RADAR_EMBEDDING_MODEL"] = "off"
os.environ["RADAR_TRANSCRIPTION_ENABLED"] = "false"
os.environ["RADAR_LOG_LEVEL"] = "WARNING"
# Chaves reais nunca vazam para a suíte comum. Com RADAR_RUN_NETWORK_TESTS=1 elas ficam, para os
# testes marcados com ``network`` (os demais usam RADAR_LLM_MODE=off e não as leem).
if os.environ.get("RADAR_RUN_NETWORK_TESTS") != "1":
    for _key in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        os.environ.pop(_key, None)
        os.environ.pop(f"RADAR_{_key}", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from radar.api.app import create_app  # noqa: E402
from radar.api.rate_limit import get_rate_limiter  # noqa: E402
from radar.config import get_settings  # noqa: E402
from radar.db import models  # noqa: E402, F401
from radar.db.base import Base  # noqa: E402
from radar.db.models import Seller, Tenant  # noqa: E402
from radar.db.session import get_engine, new_session  # noqa: E402
from radar.services.accounts import create_tenant, create_user  # noqa: E402
from radar.taxonomy import Role  # noqa: E402
from radar.testing import PASSWORD, Account, AccountFactory, FakeTranscriber  # noqa: E402
from radar.transcription import set_transcriber  # noqa: E402

IS_POSTGRES = not get_settings().is_sqlite


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_pg = pytest.mark.skip(reason="exige PostgreSQL (defina RADAR_TEST_DATABASE_URL)")
    skip_net = pytest.mark.skip(reason="exige internet e chaves reais (RADAR_RUN_NETWORK_TESTS=1)")
    run_network = os.environ.get("RADAR_RUN_NETWORK_TESTS") == "1"
    skip_slow = pytest.mark.skip(
        reason="lento: baixa e roda modelos reais (RADAR_RUN_SLOW_TESTS=1)"
    )
    run_slow = os.environ.get("RADAR_RUN_SLOW_TESTS") == "1"
    for item in items:
        if "slow" in item.keywords and not run_slow:
            item.add_marker(skip_slow)
        if "postgres" in item.keywords and not IS_POSTGRES:
            item.add_marker(skip_pg)
        if "network" in item.keywords and not run_network:
            item.add_marker(skip_net)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    engine = get_engine()
    if IS_POSTGRES:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    """Banco vazio e limitador de taxa zerado a cada teste."""
    engine = get_engine()
    with engine.begin() as conn:
        if IS_POSTGRES:
            tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
            if tables:
                conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        else:
            # Ordem reversa de dependência: filhos antes dos pais, sem desligar as chaves
            # estrangeiras (um PRAGMA dentro da transação seria ignorado e o CASCADE sumiria).
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
    limiter = get_rate_limiter()
    reset = getattr(limiter, "reset", None)
    if callable(reset):
        reset()


@pytest.fixture
def fake_transcriber() -> Iterator[FakeTranscriber]:
    """Liga a transcrição com um transcritor de mentira durante o teste."""
    fake = FakeTranscriber()
    set_transcriber(fake)
    yield fake
    set_transcriber(None, clear=True)


@pytest.fixture
def db() -> Iterator[Session]:
    """Sessão sem escopo de empresa (visão administrativa)."""
    session = new_session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="session")
def app_instance():  # type: ignore[no-untyped-def]
    return create_app()


@pytest.fixture
def client(app_instance) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with TestClient(app_instance) as test_client:
        yield test_client


@pytest.fixture
def make_tenant(db: Session) -> Callable[..., Tenant]:
    def _make(name: str | None = None, **kwargs: object) -> Tenant:
        tenant = create_tenant(db, name or f"Empresa {uuid.uuid4().hex[:6]}", **kwargs)  # type: ignore[arg-type]
        db.commit()
        return tenant

    return _make


@pytest.fixture
def make_seller(db: Session) -> Callable[..., Seller]:
    def _make(
        tenant: Tenant, name: str = "Carla Mendes", aliases: list[str] | None = None
    ) -> Seller:
        seller = Seller(tenant_id=tenant.id, display_name=name, aliases=aliases or [])
        db.add(seller)
        db.commit()
        return seller

    return _make


@pytest.fixture
def make_account(
    db: Session, client: TestClient, make_tenant: Callable[..., Tenant]
) -> AccountFactory:
    def _make(
        role: Role = Role.ADMIN,
        *,
        tenant: Tenant | None = None,
        email: str | None = None,
        seller: Seller | None = None,
    ) -> Account:
        tenant = tenant or make_tenant()
        email = email or f"{role.value}-{uuid.uuid4().hex[:8]}@example.com"
        user = create_user(
            db,
            tenant_id=tenant.id,
            email=email,
            name=f"Pessoa {role.value}",
            role=role,
            password=PASSWORD,
            seller_id=seller.id if seller else None,
        )
        db.commit()
        response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        client.cookies.clear()
        return Account(tenant=tenant, user=user, token=response.json()["access_token"])

    return _make
