"""Hash de senha com Argon2id (parâmetros padrão do argon2-cffi, alinhados à OWASP)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# Hash fixo usado para gastar o mesmo tempo quando o e-mail não existe (evita enumerar usuários).
_DUMMY_HASH = _hasher.hash("radar-dummy-password")


def burn_time() -> None:
    verify_password("senha-que-nao-confere", _DUMMY_HASH)
