"""O painel usa tipos gerados do OpenAPI: o arquivo versionado precisa acompanhar a API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI

SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api" / "openapi.json"


def test_openapi_do_frontend_esta_atualizado(app_instance: FastAPI):
    assert SNAPSHOT.exists(), "rode: uv run python scripts/export_openapi.py && npm run api:types"
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert saved == app_instance.openapi(), (
        "A API mudou: rode `uv run python scripts/export_openapi.py` e `npm run api:types` no frontend"
    )
