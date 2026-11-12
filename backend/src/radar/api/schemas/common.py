"""Schemas compartilhados pela API."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base dos schemas de saída: lê atributos de objetos ORM."""

    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class Pagination(BaseModel):
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=200, description="Itens por página")] = 50,
    offset: Annotated[int, Query(ge=0, description="Itens a pular")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


class Message(BaseModel):
    message: str
