"""Tokens de API para integrações.

Formato: ``rdr_<prefixo>_<segredo>``. O prefixo (público) localiza o registro; o banco guarda só o
SHA-256 do token inteiro. Como o segredo tem 256 bits aleatórios, um hash rápido é suficiente.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

TOKEN_SCHEME = "rdr"  # noqa: S105
_PREFIX_BYTES = 6
_SECRET_BYTES = 32


@dataclass(frozen=True, slots=True)
class GeneratedToken:
    plain: str
    prefix: str
    token_hash: str


def hash_api_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_api_token() -> GeneratedToken:
    prefix = secrets.token_hex(_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    plain = f"{TOKEN_SCHEME}_{prefix}_{secret}"
    return GeneratedToken(plain=plain, prefix=prefix, token_hash=hash_api_token(plain))


def looks_like_api_token(value: str) -> bool:
    return value.startswith(f"{TOKEN_SCHEME}_")


def extract_prefix(plain: str) -> str | None:
    parts = plain.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_SCHEME or not parts[1] or not parts[2]:
        return None
    return parts[1]


def verify_api_token(plain: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_api_token(plain), token_hash)
