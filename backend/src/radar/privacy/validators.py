"""Validadores de documentos e identificadores brasileiros.

São usados para dar precisão à camada de regex: um número com cara de CPF só é mascarado como
CPF se os dígitos verificadores baterem (ou se o texto em volta disser que é um CPF).
"""

from __future__ import annotations

import re

_DIGITS_RE = re.compile(r"\D")


def words(text: str) -> frozenset[str]:
    """Conjunto de palavras de um bloco de texto (tabelas legíveis no código)."""
    return frozenset(text.split())


#: DDDs em uso no Brasil.
VALID_DDDS: frozenset[str] = words(
    """
    11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49
    51 53 54 55 61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89
    91 92 93 94 95 96 97 98 99
    """
)


def only_digits(value: str) -> str:
    return _DIGITS_RE.sub("", value)


def is_valid_cpf(value: str) -> bool:
    digits = only_digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(digits[i]) * (size + 1 - i) for i in range(size))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


_CNPJ_WEIGHTS_1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_WEIGHTS_2 = (6, *_CNPJ_WEIGHTS_1)
_CNPJ_CLEAN_RE = re.compile(r"[.\-/\s]")


def is_valid_cnpj(value: str) -> bool:
    """Valida CNPJ numérico e o alfanumérico (em vigor a partir de julho de 2026).

    No formato novo os 12 primeiros caracteres podem ser letras maiúsculas ou dígitos; o valor de
    cada caractere é o código ASCII menos 48, e os dois dígitos verificadores continuam numéricos.
    """
    raw = _CNPJ_CLEAN_RE.sub("", value).upper()
    if len(raw) != 14 or not raw[:12].isalnum() or not raw[12:].isdigit():
        return False
    if not raw.isascii() or raw == raw[0] * 14:
        return False
    values = [ord(ch) - 48 for ch in raw]
    for weights, position in ((_CNPJ_WEIGHTS_1, 12), (_CNPJ_WEIGHTS_2, 13)):
        total = sum(v * w for v, w in zip(values[:position], weights, strict=True))
        remainder = total % 11
        check = 0 if remainder < 2 else 11 - remainder
        if check != values[position]:
            return False
    return True


def is_valid_phone_br(value: str) -> bool:
    """Telefone brasileiro com DDD (fixo ou celular), com ou sem o 55 do país."""
    digits = only_digits(value)
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]  # 0 de operadora antes do DDD de um fixo
    if len(digits) not in (10, 11) or digits[:2] not in VALID_DDDS:
        return False
    number = digits[2:]
    if len(number) == 9:
        return number[0] == "9"
    return number[0] in "2345"


def is_valid_cep(value: str) -> bool:
    digits = only_digits(value)
    return len(digits) == 8 and digits != digits[0] * 8


_PLATE_OLD_RE = re.compile(r"^[A-Z]{3}-?\d{4}$")
_PLATE_MERCOSUL_RE = re.compile(r"^[A-Z]{3}\d[A-J]\d{2}$")


def is_valid_plate(value: str) -> bool:
    """Placa no padrão antigo (ABC-1234) ou Mercosul (ABC1D23)."""
    plate = value.strip().upper()
    return bool(_PLATE_OLD_RE.match(plate) or _PLATE_MERCOSUL_RE.match(plate))


_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$"
)


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value.strip())) and ".." not in value


def passes_luhn(value: str) -> bool:
    """Algoritmo de Luhn (números de cartão)."""
    digits = only_digits(value)
    if not 13 <= len(digits) <= 19 or digits == digits[0] * len(digits):
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0
