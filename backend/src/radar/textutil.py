"""Utilidades de texto compartilhadas."""

from __future__ import annotations

import unicodedata


def plural(count: int, one: str, many: str) -> str:
    """``1 conversa``, ``3 conversas`` (e ``0 conversas``)."""
    return f"{count} {one if count == 1 else many}"


def duration_pt(minutes: float) -> str:
    """Minutos como as pessoas falam: ``45 min``, ``9 h 20 min``, ``3 dias``."""
    total = round(minutes)
    if total < 60:
        return f"{total} min"
    if total < 48 * 60:
        hours, rest = divmod(total, 60)
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return f"{round(total / (24 * 60))} dias"


def fold(text: str) -> str:
    """Minúsculas sem acento, com o mesmo comprimento do texto (as posições continuam valendo)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text.lower())
