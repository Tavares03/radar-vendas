"""Estruturas do dataset sintético (e o formato JSON delas)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class PiiAnnotation:
    type: str
    start: int
    end: int
    value: str


@dataclass(slots=True)
class SynthMessage:
    index: int
    #: ``vendedor`` ou ``cliente``.
    sender: str
    author: str
    #: Horário local, sem fuso (como no export do WhatsApp).
    timestamp: datetime
    #: ``texto`` ou ``audio`` (o texto de um áudio é a transcrição).
    kind: str
    text: str
    labels: list[str]
    pii: list[PiiAnnotation]
    act: str
    family: str
    stage: str


@dataclass(frozen=True, slots=True)
class ExpectedAlert:
    type: str
    severity: str
    #: Mensagem que é a evidência do alerta (``None`` para alertas da conversa inteira).
    message_index: int | None
    note: str = ""


@dataclass(slots=True)
class RequestRecord:
    message_index: int
    #: Pedidos que são cobrança de um anterior compartilham a mesma cadeia.
    chain: int
    answered_by: int | None = None


@dataclass(slots=True)
class ObjectionRecord:
    type: str
    message_index: int
    #: ``bem``, ``parcial``, ``mal`` ou ``sem_resposta`` (ver ``ObjectionHandling``).
    handling: str
    answered_by: int | None = None


@dataclass(slots=True)
class SynthConversation:
    id: str
    seed: int
    sector: str
    split: str
    seller_profile: str
    customer_profile: str
    outcome: str
    company: str
    seller_display: str
    customer_display: str
    messages: list[SynthMessage]
    exported_at: datetime
    expected_alerts: list[ExpectedAlert] = field(default_factory=list)
    requests: list[RequestRecord] = field(default_factory=list)
    objections: list[ObjectionRecord] = field(default_factory=list)
    generator_version: str = ""

    @property
    def families(self) -> list[str]:
        return sorted({m.family for m in self.messages})

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["exported_at"] = self.exported_at.isoformat()
        for message in data["messages"]:
            message["timestamp"] = message["timestamp"].isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthConversation:
        messages = [
            SynthMessage(
                **{
                    **m,
                    "timestamp": datetime.fromisoformat(m["timestamp"]),
                    "pii": [PiiAnnotation(**p) for p in m["pii"]],
                }
            )
            for m in data["messages"]
        ]
        return cls(
            **{
                **data,
                "messages": messages,
                "exported_at": datetime.fromisoformat(data["exported_at"]),
                "expected_alerts": [ExpectedAlert(**a) for a in data["expected_alerts"]],
                "requests": [RequestRecord(**r) for r in data["requests"]],
                "objections": [ObjectionRecord(**o) for o in data["objections"]],
            }
        )
