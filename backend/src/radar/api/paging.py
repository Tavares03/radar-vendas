"""Paginação de listagens."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from radar.api.schemas.common import Pagination


def paginate[T](
    db: Session,
    model: type[T],
    *,
    filters: Sequence[ColumnElement[bool]] = (),
    order_by: Sequence[Any],
    page: Pagination,
) -> tuple[list[T], int]:
    """Devolve ``(itens da página, total)``.

    O total é contado direto sobre o modelo (sem subconsulta) para que o filtro automático por
    empresa da sessão também valha para a contagem.
    """
    total = db.scalar(select(func.count()).select_from(model).where(*filters)) or 0
    rows = db.scalars(
        select(model).where(*filters).order_by(*order_by).limit(page.limit).offset(page.offset)
    ).all()
    return list(rows), total
