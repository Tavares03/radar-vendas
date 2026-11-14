"""Entradas e saídas da análise de uma conversa (sem banco, sem API)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from radar.playbooks import Playbook
from radar.taxonomy import MessageKind, SenderRole
from radar.tenant_settings import BusinessHours


@dataclass(frozen=True, slots=True)
class MessageInput:
    index: int
    sender: SenderRole
    #: Texto **mascarado**: é o único que a análise (e o LLM) enxerga.
    text: str
    sent_at: datetime
    kind: MessageKind = MessageKind.TEXTO
    message_id: uuid.UUID | None = None


@dataclass(slots=True)
class ConversationInput:
    messages: Sequence[MessageInput]
    playbook: Playbook
    timezone: ZoneInfo
    business_hours: BusinessHours
    #: "Agora" para a análise (silêncio do cliente, follow-up). Em evals, a hora do export.
    reference_time: datetime
    response_sla_minutes: int = 15
    follow_up_hours: int = 48
    conversation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """Achado de regra ou do classificador que o LLM vai confirmar ou refutar."""

    id: str
    type: str
    message_index: int
    evidence: str
    source: str


# ---------------------------------------------------------------- o que o LLM devolve
class CandidateReview(BaseModel):
    id: str
    confirmed: bool
    reason: str = ""


class LLMFindingProposal(BaseModel):
    type: str
    message_index: int
    quote: str
    explanation: str = ""
    confidence: float = Field(0.7, ge=0, le=1)


class ObjectionAssessment(BaseModel):
    message_index: int
    type: str
    handling: Literal["bem", "parcial", "mal", "sem_resposta"]
    answered_by: int | None = None


class RequestAssessment(BaseModel):
    message_index: int
    description: str = ""
    answered: bool
    answered_by: int | None = None


class SignalAssessment(BaseModel):
    message_index: int
    handled: bool


class LLMReport(BaseModel):
    summary: str = ""
    stage: str | None = None
    sentiment: str | None = None
    suggestion: str = ""
    reviews: list[CandidateReview] = Field(default_factory=list)
    new_findings: list[LLMFindingProposal] = Field(default_factory=list)
    objections: list[ObjectionAssessment] | None = None
    requests: list[RequestAssessment] | None = None
    signals: list[SignalAssessment] | None = None
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cached: bool = False


class LLMUnavailable(RuntimeError):
    """Nenhum provedor de LLM respondeu (ou o modo é ``off``). A análise segue sem ele."""


class LLMAnalyzer(Protocol):
    name: str

    def analyze(
        self, conversation: ConversationInput, candidates: Sequence[Candidate]
    ) -> LLMReport: ...


class MessageClassifier(Protocol):
    """Classificador próprio multirrótulo (fase de modelos próprios)."""

    name: str
    thresholds: dict[str, float]

    def predict(self, messages: Sequence[MessageInput]) -> list[dict[str, float]]: ...


# ---------------------------------------------------------------- resultado
@dataclass(slots=True)
class Finding:
    type: str
    category: str
    severity: str
    message_index: int | None
    evidence: str
    explanation: str
    #: O que cada camada disse: ``{"regra": {...}, "classificador": {...}, "llm": {...}}``.
    sources: dict[str, Any]
    start: int | None = None
    end: int | None = None
    confidence: float = 1.0
    #: Achado de regra que o LLM não confirmou: continua, mas marcado.
    contested: bool = False


@dataclass(slots=True)
class Criterion:
    id: str
    label: str
    points: float
    maximum: int
    justification: str
    #: Calculado só com heurística (sem o LLM para confirmar).
    estimated: bool = False


@dataclass(slots=True)
class ResponseMetrics:
    #: ``(mensagem do cliente, resposta do vendedor, minutos úteis)``.
    replies: list[tuple[int, int, int]] = field(default_factory=list)
    median_reply_minutes: float | None = None
    max_reply_minutes: int | None = None
    silence_hours: float = 0.0
    follow_up_missing: bool = False
    customer_closed: bool = False


@dataclass(slots=True)
class ConversationAnalysis:
    score: int
    criteria: list[Criterion]
    findings: list[Finding]
    message_labels: dict[int, list[str]]
    objections: list[ObjectionAssessment]
    requests: list[RequestAssessment]
    metrics: ResponseMetrics
    layers: list[str]
    discarded: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    suggestion: str = ""
    sentiment: str | None = None
    stage: str | None = None
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    injection_suspected: bool = False
    llm_error: str | None = None
    llm: dict[str, Any] = field(default_factory=dict)
