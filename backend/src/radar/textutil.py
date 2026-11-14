"""Utilidades de texto compartilhadas."""

from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    """Minúsculas sem acento, com o mesmo comprimento do texto (as posições continuam valendo)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text.lower())
