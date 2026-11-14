"""Cache de respostas do LLM em disco (``RADAR_DATA_DIR/cache/llm``).

A mesma conversa analisada de novo com o mesmo playbook não gasta cota. A chave é o hash do
prompt; o conteúdo é o JSON já validado. Como o prompt só tem texto mascarado, o cache também.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class FileCache:
    def __init__(self, folder: Path, *, ttl_seconds: int) -> None:
        self.folder = folder
        self.ttl = ttl_seconds

    def _path(self, key: str) -> Path:
        return self.folder / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            stat = path.stat()
        except OSError:
            return None
        if self.ttl > 0 and time.time() - stat.st_mtime > self.ttl:
            path.unlink(missing_ok=True)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            return  # cache é otimização: falhar aqui não pode derrubar a análise
