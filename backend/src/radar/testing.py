"""Utilitários para testes (do próprio projeto e de quem integra com ele)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from radar.db.models import Tenant, User

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
