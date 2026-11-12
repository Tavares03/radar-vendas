"""Schemas de importações, conversas e mensagens."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from radar.api.schemas.common import ApiModel
from radar.taxonomy import (
    ConversationStatus,
    ImportSource,
    ImportStatus,
    MessageKind,
    SenderRole,
    TranscriptionStatus,
)


class SellerBrief(ApiModel):
    id: uuid.UUID
    display_name: str


class ImportOut(ApiModel):
    id: uuid.UUID
    source: ImportSource
    status: ImportStatus
    filename: str
    size_bytes: int
    conversation_id: uuid.UUID | None
    error: str
    stats: dict[str, Any]
    created_by_label: str
    created_at: datetime
    finished_at: datetime | None
    #: Verdadeiro quando o mesmo arquivo já tinha sido importado: nada foi reprocessado.
    duplicate: bool = False


class ConversationOut(ApiModel):
    id: uuid.UUID
    seller: SellerBrief | None
    customer_label: str
    source: ImportSource
    external_id: str | None
    playbook: str
    status: ConversationStatus
    status_detail: str
    #: ``alta`` | ``media`` | ``baixa``. Abaixo de ``alta``, vale confirmar quem é o vendedor.
    role_confidence: str
    warnings: list[str]
    started_at: datetime | None
    last_message_at: datetime | None
    message_count: int
    seller_message_count: int
    customer_message_count: int
    audio_count: int
    created_at: datetime


class ParticipantOut(BaseModel):
    key: str
    role: SenderRole
    label: str
    seller_id: uuid.UUID | None = None
    confidence: str = "alta"
    reason: str = ""
    #: Nome como veio na origem. Só preenchido quando os dados são revelados.
    name: str | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    position: int
    sent_at: datetime
    sender_role: SenderRole
    sender_key: str
    sender_label: str
    kind: MessageKind
    #: Texto mascarado por padrão; texto original quando ``revealed`` é verdadeiro.
    text: str
    #: Falso enquanto a etapa de privacidade não rodou (o texto ainda não pode ser mostrado).
    text_available: bool
    revealed: bool
    pii_spans: list[dict[str, Any]]
    has_audio: bool
    audio_seconds: float | None
    transcription_status: TranscriptionStatus
    edited: bool


class ConversationDetail(ConversationOut):
    participants: list[ParticipantOut]
    messages: list[MessageOut]
    revealed: bool
    #: Nome ou telefone do cliente na origem. Só com ``reveal=true``.
    customer_name: str | None = None
    raw_purged: bool = False


class MessageIn(BaseModel):
    sent_at: datetime = Field(description="Data e hora. Sem fuso, vale o fuso da empresa.")
    sender: Literal["vendedor", "cliente"]
    text: str = Field(default="", max_length=20000)
    kind: MessageKind = MessageKind.TEXTO
    external_id: str | None = Field(
        default=None, max_length=200, description="Id da mensagem no seu sistema (evita duplicar)."
    )


class ConversationIn(BaseModel):
    external_id: str | None = Field(
        default=None,
        max_length=200,
        description="Id da conversa no seu sistema. Reenviar com o mesmo id acrescenta mensagens.",
    )
    seller_id: uuid.UUID | None = None
    seller_name: str | None = Field(default=None, max_length=200)
    customer_name: str | None = Field(default=None, max_length=200)
    customer_phone: str | None = Field(default=None, max_length=40)
    playbook: str | None = Field(default=None, max_length=80)
    messages: list[MessageIn] = Field(min_length=1, max_length=5000)


class ConversationIngested(BaseModel):
    conversation: ConversationOut
    created: bool
    new_messages: int
    duplicate_messages: int


class ConversationUpdate(BaseModel):
    seller_id: uuid.UUID | None = Field(
        default=None, description="Atribui a conversa a outro vendedor cadastrado."
    )
    playbook: str | None = Field(default=None, max_length=80)
    seller_participant: str | None = Field(
        default=None,
        max_length=64,
        description="`key` do participante que é o vendedor (corrige papéis trocados).",
    )
