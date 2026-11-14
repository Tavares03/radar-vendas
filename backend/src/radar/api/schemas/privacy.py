"""Schemas de privacidade: titulares e retenção."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]


class SubjectQuery(BaseModel):
    identifiers: list[Identifier] = Field(
        min_length=1,
        max_length=10,
        description=(
            "Dados que identificam o titular: nome completo, telefone, CPF, e-mail, CNPJ… "
            "Vão no corpo (não na URL) para não aparecerem em logs."
        ),
    )


class SubjectDeleteIn(SubjectQuery):
    confirm: Literal[True] = Field(description="Precisa ser `true`: a exclusão não tem volta.")


class SubjectConversationOut(BaseModel):
    conversation_id: uuid.UUID
    #: ``participante``: o titular é o cliente; ``mencionado``: um dado dele aparece no texto.
    relation: Literal["participante", "mencionado"]
    mentions: int
    customer_label: str
    seller_name: str | None
    message_count: int
    last_message_at: datetime | None


class SubjectSearchOut(BaseModel):
    conversations: list[SubjectConversationOut]


class SubjectDeletionOut(BaseModel):
    conversations_deleted: int
    messages_redacted: int


class RetentionReportOut(BaseModel):
    dry_run: bool
    raw_messages_purged: int
    masked_before_purge: int
    media_files_deleted: int
    conversations_deleted: int


class RetentionPolicyOut(BaseModel):
    retention_raw_days: int
    retention_media_days: int
    retention_conversation_days: int


class RetentionStatusOut(BaseModel):
    policy: RetentionPolicyOut
    #: O que a próxima execução apagaria hoje (simulação, nada é alterado).
    pending: RetentionReportOut
