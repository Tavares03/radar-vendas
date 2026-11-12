"""Utilitários para testes (do próprio projeto e de quem integra com ele)."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from radar.db.models import Tenant, User
from radar.transcription.base import Transcript, TranscriptionError

#: Senha usada pelas contas criadas nos testes.
PASSWORD = "senha-forte-123"  # noqa: S105


@dataclass
class Account:
    """Um usuário de teste já autenticado."""

    tenant: Tenant
    user: User
    token: str
    password: str = PASSWORD

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


AccountFactory = Callable[..., Account]


def make_zip(files: Mapping[str, bytes | str]) -> bytes:
    """Monta um zip em memória a partir de ``{nome: conteúdo}``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8") if isinstance(content, str) else content)
    return buffer.getvalue()


@dataclass
class FakeTranscriber:
    """Transcritor de mentira: devolve um texto fixo e registra o que foi pedido."""

    text: str = "transcrição de teste"
    fail: bool = False
    calls: list[Path] = field(default_factory=list)

    def transcribe(self, path: Path) -> Transcript:
        self.calls.append(path)
        if self.fail:
            raise TranscriptionError("falha simulada")
        if not path.is_file():
            raise TranscriptionError("arquivo de áudio não encontrado")
        return Transcript(text=self.text, language="pt", duration_seconds=4.2, model="fake")
