"""Tipos de coluna portáveis entre PostgreSQL (produção) e SQLite (testes e modo leve)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine

#: Dimensão dos embeddings de busca (multilingual-e5-small).
EMBEDDING_DIM = 384

#: JSON genérico; vira JSONB no PostgreSQL.
JSONType = JSON().with_variant(JSONB(), "postgresql")

#: Vetor pgvector no PostgreSQL; lista JSON no SQLite (a busca cai para cosseno em Python).
EmbeddingType = Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite")


class UtcDateTime(TypeDecorator[datetime]):
    """``datetime`` sempre com fuso, guardado em UTC.

    O SQLite descarta o fuso; aqui ele é reposto na leitura. Gravar um ``datetime`` ingênuo é
    erro de programação e levanta ``ValueError``.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime sem fuso horário; use datetime.now(UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class StrEnumType[E: StrEnum](TypeDecorator[E]):
    """Guarda um ``StrEnum`` como texto (sem ENUM nativo, para migrations simples)."""

    impl = String(40)
    cache_ok = True

    def __init__(self, enum_cls: type[E], length: int = 40) -> None:
        super().__init__(length)
        self.enum_cls = enum_cls

    def process_bind_param(self, value: E | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return self.enum_cls(value).value

    def process_result_value(self, value: str | None, dialect: Dialect) -> E | None:
        if value is None:
            return None
        return self.enum_cls(value)


class EncryptedText(TypeDecorator[str]):
    """Texto cifrado em repouso (Fernet). A chave vem de :mod:`radar.privacy.crypto`."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        from radar.privacy.crypto import encrypt_text

        return encrypt_text(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        from radar.privacy.crypto import decrypt_text

        return decrypt_text(value)
