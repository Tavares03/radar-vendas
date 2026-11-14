"""Mascaramento, detector em camadas e a trava contra texto sem máscara."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from radar.privacy.detection import PiiSpan
from radar.privacy.detector import PiiDetector
from radar.privacy.guard import UnmaskedDataError, ensure_masked
from radar.privacy.masking import MaskedSpan, MaskedText, mask, placeholder
from radar.taxonomy import PiiType

CPF = "529.982.247-25"


# ---------------------------------------------------------------- mask()
def test_mask_troca_cada_trecho_pelo_tipo_e_recalcula_posicoes():
    text = f"CPF {CPF}, tel (11) 91234-5678."
    spans = [
        PiiSpan(PiiType.CPF, 4, 4 + len(CPF), CPF),
        PiiSpan(PiiType.TELEFONE, 24, 39, "(11) 91234-5678"),
    ]

    masked = mask(text, spans)

    assert masked.text == "CPF [CPF], tel [TELEFONE]."
    assert masked.spans == (
        MaskedSpan(PiiType.CPF, 4, 9),
        MaskedSpan(PiiType.TELEFONE, 15, 25),
    )
    for span in masked.spans:
        assert masked.text[span.start : span.end] == placeholder(span.type)
    assert masked.span_dicts() == [
        {"type": "CPF", "start": 4, "end": 9},
        {"type": "TELEFONE", "start": 15, "end": 25},
    ]


def test_mask_sem_trechos_devolve_o_texto():
    assert mask("nada aqui", []) == MaskedText("nada aqui", ())


def test_mask_resolve_sobreposicao_antes_de_trocar():
    text = "roberto@exemplo.com"
    spans = [
        PiiSpan(PiiType.NOME_PESSOA, 0, 7, "roberto", source="participante"),
        PiiSpan(PiiType.EMAIL, 0, len(text), text),
    ]
    assert mask(text, spans).text == "[EMAIL]"


# ---------------------------------------------------------------- detector em camadas
def test_detector_junta_regex_e_nomes_dos_participantes():
    detector = PiiDetector()
    text = f"Oi Roberto, recebi seu CPF {CPF}"

    masked = detector.mask(text, known_names=["Roberto Lima"])

    assert masked.text == "Oi [NOME_PESSOA], recebi seu CPF [CPF]"
    assert [(s.type, s.text, s.source) for s in masked.found] == [
        (PiiType.NOME_PESSOA, "Roberto", "participante"),
        (PiiType.CPF, CPF, "regex"),
    ]


def test_detector_pode_deixar_nomes_de_fora():
    detector = PiiDetector()
    text = f"meu nome é Roberto Lima e o CPF {CPF}"

    masked = detector.mask(text, known_names=["Roberto Lima"], mask_names=False)

    assert masked.text == "meu nome é Roberto Lima e o CPF [CPF]"


class FakeNer:
    name = "ner-falso"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def predict(self, texts: Sequence[str]) -> list[list[PiiSpan]]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("modelo quebrou")
        result = []
        for text in texts:
            start = text.find("Fulano")
            result.append(
                [PiiSpan(PiiType.NOME_PESSOA, start, start + 6, "Fulano", "ner", 0.91)]
                if start >= 0
                else []
            )
        return result


def test_detector_usa_o_ner_quando_existe_e_processa_em_lote():
    ner = FakeNer()
    detector = PiiDetector(ner=ner)

    results = detector.mask_many(["falei com o fulano e o Fulano", f"cpf {CPF}"])

    assert ner.calls == [["falei com o fulano e o Fulano", f"cpf {CPF}"]]
    assert results[0].text == "falei com o fulano e o [NOME_PESSOA]"
    assert results[0].found[0].source == "ner"
    assert results[1].text == "cpf [CPF]"
    assert detector.layers == ("regex", "participantes", "ner:ner-falso")


def test_falha_do_ner_nao_derruba_a_mascara_por_regex():
    detector = PiiDetector(ner=FakeNer(fail=True))

    masked = detector.mask(f"Fulano, cpf {CPF}")

    assert masked.text == "Fulano, cpf [CPF]"


def test_ner_nao_mascara_nome_quando_a_empresa_desliga():
    detector = PiiDetector(ner=FakeNer())
    assert detector.mask("o Fulano ligou", mask_names=False).text == "o Fulano ligou"


# ---------------------------------------------------------------- trava
def test_trava_aceita_texto_mascarado():
    ensure_masked("Oi [NOME_PESSOA], seu CPF [CPF] e tel [TELEFONE] estão ok. Parcela R$ 850,00")


@pytest.mark.parametrize(
    "text",
    [
        f"meu cpf {CPF}",
        "email ana@exemplo.com",
        "zap (11) 91234-5678",
        "cnpj 11.222.333/0001-81",
        "pix 123e4567-e89b-42d3-a456-426614174000",
        "cartão 4111 1111 1111 1111",
    ],
)
def test_trava_recusa_texto_com_dado_pessoal(text: str):
    with pytest.raises(UnmaskedDataError) as caught:
        ensure_masked(text)
    # A mensagem de erro não pode vazar o dado que tentou proteger.
    assert text.split()[-1] not in str(caught.value)


@pytest.mark.parametrize(
    "text",
    [
        f"Oi, meu nome é Roberto Lima, CPF {CPF}, moro na Rua das Flores, 123, CEP 01310-100",
        "ag 1234 cc 56789-0, placa ABC1D23, rg 12.345.678-9, cel 91234-5678",
        "pix 123e4567-e89b-42d3-a456-426614174000 ou ana@exemplo.com",
    ],
)
def test_texto_mascarado_pelo_detector_passa_na_trava(text: str):
    ensure_masked(PiiDetector().mask(text).text)
