"""Configurações por empresa, guardadas como JSON em ``tenants.settings``."""

from __future__ import annotations

from datetime import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from radar.taxonomy import Role, Severity


class BusinessHours(BaseModel):
    """Horário de atendimento usado para medir tempo de resposta."""

    model_config = ConfigDict(extra="forbid")

    start: time = time(8, 0)
    end: time = time(18, 0)
    #: Dias úteis, com segunda = 0 e domingo = 6.
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])

    @field_validator("weekdays")
    @classmethod
    def _valid_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("dias da semana vão de 0 (segunda) a 6 (domingo)")
        return sorted(set(value))


class TenantSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timezone: str = "America/Sao_Paulo"
    business_hours: BusinessHours = Field(default_factory=BusinessHours)

    # ---- LGPD / retenção (0 = nunca apagar) ----
    retention_raw_days: int = Field(default=90, ge=0)
    retention_media_days: int = Field(default=30, ge=0)
    retention_conversation_days: int = Field(default=0, ge=0)
    reveal_roles: list[Role] = Field(
        default_factory=lambda: [Role.ADMIN, Role.GESTOR, Role.AUDITOR]
    )
    mask_person_names: bool = True
    #: Consentimento para usar correções do painel no retreino local.
    feedback_training_consent: bool = False

    # ---- análise ----
    llm_mode: Literal["herdar", "cloud", "local", "off"] = "herdar"
    response_sla_minutes: int = Field(default=15, ge=1)
    follow_up_hours: int = Field(default=48, ge=1)

    # ---- alertas ----
    notify_min_severity: Severity = Severity.CRITICO


def load_tenant_settings(raw: dict[str, object] | None) -> TenantSettings:
    return TenantSettings.model_validate(raw or {})
