"""Schemas de análise, alertas e playbooks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from radar.api.schemas.common import ApiModel
from radar.taxonomy import AlertStatus


class UserBrief(ApiModel):
    id: uuid.UUID
    name: str
    email: str


class AlertOut(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID | None
    message_index: int | None
    type: str
    #: Nome do tipo em português ("Promessa indevida").
    label: str = ""
    category: str
    severity: str
    #: Trecho da mensagem, já mascarado.
    evidence: str
    explanation: str
    #: O que cada camada disse (regra, classificador, LLM, métrica).
    sources: dict[str, Any]
    confidence: float
    contested: bool
    status: AlertStatus
    assigned_to: UserBrief | None = None
    review_note: str
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    customer_label: str = ""
    seller_name: str | None = None


class AlertUpdate(BaseModel):
    status: AlertStatus | None = None
    assigned_to_user_id: uuid.UUID | None = None
    unassign: bool = Field(default=False, description="Tira o responsável do alerta.")
    note: str | None = Field(default=None, max_length=2000)


class CriterionOut(BaseModel):
    id: str
    label: str
    points: float
    maximum: int
    justification: str
    estimated: bool


class AnalysisOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: datetime
    score: int
    playbook: str
    playbook_version: int
    summary: str
    suggestion: str
    sentiment: str | None
    stage: str | None
    #: Camadas que participaram: ``regra``, ``classificador``, ``metrica``, ``llm``.
    layers: list[str]
    criteria: list[CriterionOut]
    alerts: list[AlertOut]
    objections: list[dict[str, Any]]
    requests: list[dict[str, Any]]
    metrics: dict[str, Any]
    strengths: list[str]
    improvements: list[str]
    llm: dict[str, Any]
    duration_ms: int


class PlaybookSummary(BaseModel):
    slug: str
    name: str
    #: ``padrao`` (vem com o Radar) ou ``empresa`` (escrito pela empresa).
    origin: Literal["padrao", "empresa"]
    version: int
    description: str = ""


class PlaybookDetail(PlaybookSummary):
    yaml: str
    #: O playbook já validado e com a herança resolvida.
    playbook: dict[str, Any]


class PlaybookIn(BaseModel):
    yaml: str = Field(min_length=1, max_length=200_000)


class PlaybookTestMessage(BaseModel):
    sender: Literal["vendedor", "cliente"]
    text: str = Field(max_length=5000)


class PlaybookTestIn(BaseModel):
    messages: list[PlaybookTestMessage] = Field(min_length=1, max_length=200)
    yaml: str | None = Field(
        default=None, max_length=200_000, description="Testa um rascunho em vez do playbook salvo."
    )


class RuleHitOut(BaseModel):
    message_index: int
    rule_id: str
    type: str
    severity: str | None
    evidence: str
    explanation: str


class PlaybookTestOut(BaseModel):
    hits: list[RuleHitOut]
    disclosures: dict[str, int | None]
