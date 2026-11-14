"""Validadores de documentos brasileiros (todos os números são gerados, nenhum é real)."""

from __future__ import annotations

import pytest

from radar.privacy.validators import (
    is_valid_cep,
    is_valid_cnpj,
    is_valid_cpf,
    is_valid_email,
    is_valid_phone_br,
    is_valid_plate,
    only_digits,
    passes_luhn,
)


def test_only_digits_remove_pontuacao():
    assert only_digits("529.982.247-25") == "52998224725"


@pytest.mark.parametrize("value", ["529.982.247-25", "52998224725", "111.444.777-35"])
def test_cpf_valido(value: str):
    assert is_valid_cpf(value)


@pytest.mark.parametrize(
    "value",
    [
        "529.982.247-24",  # dígito verificador errado
        "529.982.247-15",  # primeiro dígito errado
        "111.111.111-11",  # sequência repetida passa na conta, mas não existe
        "5299822472",  # curto
        "529982247250",  # longo
        "",
    ],
)
def test_cpf_invalido(value: str):
    assert not is_valid_cpf(value)


@pytest.mark.parametrize(
    "value",
    [
        "11.222.333/0001-81",
        "11222333000181",
        "10.000.008/0001-01",  # resto 0 na conta: dígito verificador vira 0
        "12.ABC.345/01DE-35",  # alfanumérico (exemplo oficial da Receita)
        "12abc34501de35",  # minúsculas são normalizadas
    ],
)
def test_cnpj_valido(value: str):
    assert is_valid_cnpj(value)


@pytest.mark.parametrize(
    "value",
    [
        "11.222.333/0001-80",
        "12.ABC.345/01DE-36",
        "00.000.000/0000-00",
        "11.222.333/0001",
        "12.ABC.345/01DE-3X",  # dígito verificador precisa ser número
        "1Ç.222.333/0001-81",  # só ASCII
    ],
)
def test_cnpj_invalido(value: str):
    assert not is_valid_cnpj(value)


@pytest.mark.parametrize(
    "value",
    [
        "(11) 91234-5678",
        "11912345678",
        "+55 11 91234-5678",
        "5511912345678",
        "(21) 3456-7890",  # fixo
        "011 3456-7890",  # 0 de operadora
        "+55 (61) 2345-6789",
    ],
)
def test_telefone_valido(value: str):
    assert is_valid_phone_br(value)


@pytest.mark.parametrize(
    "value",
    [
        "(20) 91234-5678",  # DDD inexistente
        "(11) 81234-5678",  # celular com 9 dígitos precisa começar com 9
        "(11) 1234-5678",  # fixo não começa com 1
        "91234-5678",  # sem DDD
        "123",
    ],
)
def test_telefone_invalido(value: str):
    assert not is_valid_phone_br(value)


@pytest.mark.parametrize(("value", "expected"), [("01310-100", True), ("01310100", True)])
def test_cep_valido(value: str, expected: bool):
    assert is_valid_cep(value) is expected


@pytest.mark.parametrize("value", ["0131-100", "00000-000", "013101000"])
def test_cep_invalido(value: str):
    assert not is_valid_cep(value)


@pytest.mark.parametrize("value", ["ABC-1234", "ABC1234", "abc1d23", "BRA2E19"])
def test_placa_valida(value: str):
    assert is_valid_plate(value)


@pytest.mark.parametrize("value", ["AB-1234", "ABC12345", "ABC1K23", "1BC1234"])
def test_placa_invalida(value: str):
    assert not is_valid_plate(value)


@pytest.mark.parametrize("value", ["ana.souza@exemplo.com", "a+b@sub.exemplo.com.br"])
def test_email_valido(value: str):
    assert is_valid_email(value)


@pytest.mark.parametrize("value", ["ana@", "@exemplo.com", "ana..souza@exemplo.com", "ana@exemplo"])
def test_email_invalido(value: str):
    assert not is_valid_email(value)


def test_luhn():
    assert passes_luhn("4111 1111 1111 1111")
    assert not passes_luhn("4111 1111 1111 1112")
    assert not passes_luhn("0000 0000 0000 0000")
