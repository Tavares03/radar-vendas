"""Dados pessoais falsos: válidos onde precisam ser e reconhecidos pelo detector do Radar."""

from __future__ import annotations

import random
import re

import pytest

from radar.privacy.detection import detect_regex
from radar.privacy.validators import (
    is_valid_cep,
    is_valid_cnpj,
    is_valid_cpf,
    is_valid_email,
    is_valid_phone_br,
    is_valid_plate,
    passes_luhn,
)
from radar.taxonomy import PiiType
from radar_synth.fake import FakeData

SEEDS = range(40)


def _fake(seed: int) -> FakeData:
    return FakeData(random.Random(seed))


@pytest.mark.parametrize("seed", SEEDS)
def test_documentos_sao_validos(seed: int):
    fake = _fake(seed)
    assert is_valid_cpf(fake.cpf())
    assert is_valid_cpf(fake.cpf(formatted=False))
    assert is_valid_cnpj(fake.cnpj())
    assert is_valid_cnpj(fake.cnpj(alphanumeric=True))
    assert is_valid_phone_br(fake.phone())
    assert is_valid_cep(fake.cep())
    assert is_valid_plate(fake.plate())
    assert passes_luhn(fake.card_number())
    assert is_valid_email(fake.email("Ana Paula Souza"))


def test_mesma_semente_gera_os_mesmos_dados():
    a, b = _fake(7), _fake(7)
    assert [a.cpf(), a.full_name(), a.phone(), a.address()] == [
        b.cpf(),
        b.full_name(),
        b.phone(),
        b.address(),
    ]


def test_formatos_de_telefone_variam_e_sao_validos():
    fake = _fake(1)
    styles = {fake.phone() for _ in range(200)}
    assert any(s.startswith("(") for s in styles)
    assert any(s.startswith("+55") for s in styles)
    assert any(s.isdigit() for s in styles)
    assert all(is_valid_phone_br(s) for s in styles)


def test_email_usa_dominios_ficticios():
    fake = _fake(3)
    for _ in range(100):
        domain = fake.email("João da Silva").split("@")[1]
        assert re.search(r"exemplo|teste|example|\.test$", domain), domain


@pytest.mark.parametrize("seed", range(15))
def test_detector_do_radar_reconhece_cada_dado_falso_com_o_tipo_certo(seed: int):
    fake = _fake(seed)
    samples = {
        PiiType.CPF: f"meu cpf é {fake.cpf(formatted=seed % 2 == 0)}",
        PiiType.CNPJ: f"o cnpj é {fake.cnpj(alphanumeric=seed % 3 == 0)}",
        PiiType.TELEFONE: f"meu cel é {fake.phone()}",
        PiiType.EMAIL: f"email {fake.email(fake.full_name())}",
        PiiType.CEP: f"cep {fake.cep()}",
        PiiType.PLACA: f"placa {fake.plate()}",
        PiiType.PIX: f"chave pix {fake.pix_random_key()}",
        PiiType.RG: f"rg {fake.rg()}",
        PiiType.ENDERECO: f"moro na {fake.address()}",
    }
    for kind, text in samples.items():
        found = detect_regex(text)
        assert [span.type for span in found] == [kind], (text, found)


def test_conta_e_agencia():
    fake = _fake(5)
    agency, account = fake.bank_account()
    assert re.fullmatch(r"\d{4}", agency)
    assert re.fullmatch(r"\d{4,8}-\d", account)


def test_nomes_tem_nome_e_sobrenome():
    fake = _fake(11)
    for _ in range(50):
        first, *rest = fake.full_name().split()
        assert first[0].isupper()
        assert rest
