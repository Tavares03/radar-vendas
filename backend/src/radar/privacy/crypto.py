"""Cifragem em repouso e hashes com chave.

- O texto bruto das mensagens é cifrado com Fernet (AES-128-CBC + HMAC-SHA256). A chave é derivada
  de ``RADAR_SECRET_KEY`` com HKDF, então não há uma segunda chave para administrar.
- Identificadores de titulares (CPF, telefone, e-mail) nunca são guardados em claro para busca:
  guardamos um HMAC-SHA256 por empresa, o que permite localizar um titular sem armazenar o dado.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import unicodedata
import uuid
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from radar.config import get_settings

_ENC_PREFIX = "enc:v1:"


class DecryptionError(RuntimeError):
    """O texto não pôde ser decifrado (chave trocada ou dado corrompido)."""


def _derive(purpose: bytes, length: int = 32) -> bytes:
    secret = get_settings().secret_key.get_secret_value().encode("utf-8")
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=b"radar-vendas", info=purpose)
    return hkdf.derive(secret)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_derive(b"text-encryption")))


@lru_cache(maxsize=1)
def _hmac_key() -> bytes:
    return _derive(b"subject-index")


def reset_crypto_cache() -> None:
    """Descarta as chaves derivadas (usado em testes que trocam o segredo)."""
    _fernet.cache_clear()
    _hmac_key.cache_clear()


def encrypt_text(plain: str) -> str:
    token = _fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def decrypt_text(stored: str) -> str:
    if not stored.startswith(_ENC_PREFIX):
        # Dado legado gravado antes da cifragem: devolve como está.
        return stored
    try:
        return _fernet().decrypt(stored[len(_ENC_PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Não foi possível decifrar o texto. A RADAR_SECRET_KEY foi alterada?"
        ) from exc


def normalize_identifier(value: str) -> str:
    """Forma canônica de um identificador para comparação.

    E-mails ficam em minúsculas; números (CPF, CNPJ, telefone) ficam só com dígitos, e telefones
    brasileiros perdem o ``55`` inicial; nomes ficam sem acento, em minúsculas e sem espaço duplo.
    """
    text = value.strip()
    if "@" in text:
        return text.lower()
    digits = re.sub(r"\D", "", text)
    letters = re.sub(r"[\W\d_]", "", text)
    if digits and len(digits) >= len(letters):
        if len(digits) in (12, 13) and digits.startswith("55"):
            digits = digits[2:]
        return digits
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_accents).strip().lower()


def subject_hash(tenant_id: uuid.UUID, value: str) -> str:
    """HMAC-SHA256 de um identificador, com escopo de empresa."""
    message = tenant_id.bytes + b"|" + normalize_identifier(value).encode("utf-8")
    return hmac.new(_hmac_key(), message, hashlib.sha256).hexdigest()


def pseudonym(tenant_id: uuid.UUID, value: str, prefix: str = "Cliente") -> str:
    """Pseudônimo estável e legível, por exemplo ``Cliente 7F3A``."""
    return f"{prefix} {subject_hash(tenant_id, value)[:4].upper()}"
