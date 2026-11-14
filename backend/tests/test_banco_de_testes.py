"""O banco dos testes precisa se comportar como o de produção nas regras de integridade."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from radar.config import get_settings
from radar.db.session import get_engine


@pytest.mark.skipif(not get_settings().is_sqlite, reason="só se aplica ao SQLite")
def test_sqlite_aplica_chaves_estrangeiras_entre_os_testes(db: Session):
    # A limpeza entre testes não pode deixar ON DELETE CASCADE desligado: senão um teste passa
    # no SQLite e falha no PostgreSQL (ou o contrário).
    with get_engine().connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
