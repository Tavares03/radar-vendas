"""Bancos de templates: estrutura, rótulos coerentes e nada de dado pessoal literal."""

from __future__ import annotations

import re

import pytest

from radar.privacy.detection import detect_regex
from radar.taxonomy import CUSTOMER_LABELS, SELLER_LABELS, SenderRole
from radar_synth.banks import PII_SLOTS, REQUIRED_ACTS, SECTORS, load_bank

_SLOT_RE = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("sector", SECTORS)
def test_banco_tem_todos_os_atos_que_o_gerador_usa(sector: str):
    bank = load_bank(sector)
    missing = [act for act in REQUIRED_ACTS if act not in bank.acts]
    assert missing == []


@pytest.mark.parametrize("sector", SECTORS)
def test_cada_ato_tem_familias_suficientes_para_os_tres_splits(sector: str):
    bank = load_bank(sector)
    few = {act: len(t.families) for act, t in bank.acts.items() if len(t.families) < 3}
    assert few == {}


@pytest.mark.parametrize("sector", SECTORS)
def test_rotulos_combinam_com_quem_fala(sector: str):
    bank = load_bank(sector)
    for act in bank.acts.values():
        allowed = SELLER_LABELS if act.role is SenderRole.VENDEDOR else CUSTOMER_LABELS
        assert set(act.labels) <= allowed, act.name


@pytest.mark.parametrize("sector", SECTORS)
def test_todo_slot_tem_valor(sector: str):
    bank = load_bank(sector)
    for act in bank.acts.values():
        for template in act.templates:
            for slot in _SLOT_RE.findall(template.text):
                assert slot in PII_SLOTS or slot in bank.vocab, (sector, template.family, slot)


@pytest.mark.parametrize("sector", SECTORS)
def test_vocabulario_nao_tem_dado_pessoal(sector: str):
    bank = load_bank(sector)
    for slot, values in bank.vocab.items():
        for value in values:
            assert detect_regex(value) == [], (slot, value)


@pytest.mark.parametrize("sector", SECTORS)
def test_templates_nao_tem_dado_pessoal_literal(sector: str):
    bank = load_bank(sector)
    for act in bank.acts.values():
        for template in act.templates:
            literal = _SLOT_RE.sub("…", template.text)
            assert detect_regex(literal) == [], (template.family, literal)


def test_ids_de_familia_sao_unicos_e_trazem_o_setor_de_origem():
    seen: dict[str, str] = {}
    for sector in SECTORS:
        for act in load_bank(sector).acts.values():
            for family in act.families:
                owner = family.split(".")[0]
                assert owner in {"comum", sector}, family
                seen.setdefault(family, act.name)
                assert seen[family] == act.name


def test_rotulo_fica_na_ultima_parte_das_mensagens_picotadas():
    # Convenção: "a || b" pode virar duas mensagens; o rótulo do ato vai para a última parte.
    # Por isso a parte rotulada não pode ser só uma saudação curta.
    for sector in SECTORS:
        for act in load_bank(sector).acts.values():
            if not act.labels:
                continue
            for template in act.templates:
                last = template.text.split("||")[-1].strip()
                assert len(last) >= 8, (template.family, last)
