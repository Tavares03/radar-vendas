"""Exporta o OpenAPI da API para o frontend (gera os tipos do cliente tipado).

Uso: ``uv run python scripts/export_openapi.py`` e depois ``npm run api:types`` em ``frontend/``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "api" / "openapi.json"


def render() -> str:
    os.environ.setdefault("RADAR_DISABLE_ENV_FILE", "1")
    os.environ.setdefault("RADAR_ENVIRONMENT", "test")
    from radar.api.app import create_app

    return json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(), encoding="utf-8", newline="\n")
    print(f"OpenAPI gravado em {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
