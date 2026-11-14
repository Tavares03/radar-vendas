"""Os testes do gerador nunca leem o .env de quem desenvolve nem usam chaves reais."""

from __future__ import annotations

import os

os.environ["RADAR_DISABLE_ENV_FILE"] = "1"
for _key in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(_key, None)
    os.environ.pop(f"RADAR_{_key}", None)
