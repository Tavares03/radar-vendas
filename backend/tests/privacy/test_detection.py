"""Detecção de dados pessoais por regex, validadores e contexto (camada 1).

Todos os dados são sintéticos: CPFs e CNPJs válidos só na matemática, telefones e nomes inventados.
"""

from __future__ import annotations

import pytest

from radar.privacy.detection import detect_known_names, detect_regex
from radar.taxonomy import PiiType


def found(text: str) -> list[tuple[str, str]]:
    return [(span.type.value, text[span.start : span.end]) for span in detect_regex(text)]


def test_spans_apontam_para_o_trecho_original():
    text = "meu cpf: 529.982.247-25 ok"
    (span,) = detect_regex(text)
    assert span.type is PiiType.CPF
    assert text[span.start : span.end] == "529.982.247-25"
    assert span.text == "529.982.247-25"
    assert span.source == "regex"


# ---------------------------------------------------------------- CPF
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Meu CPF é 529.982.247-25", [("CPF", "529.982.247-25")]),
        ("cpf 52998224725 por favor", [("CPF", "52998224725")]),
        # Formatado como CPF, mesmo com dígito errado: digitação errada continua sendo dado pessoal.
        ("segue 529.982.247-24", [("CPF", "529.982.247-24")]),
        # Sem formatação e inválido, mas o texto diz que é CPF.
        ("meu cpf é 12345678900", [("CPF", "12345678900")]),
        ("CPF:111.444.777-35.", [("CPF", "111.444.777-35")]),
    ],
)
def test_cpf(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


def test_onze_digitos_sem_contexto_que_nao_sao_cpf_viram_telefone():
    assert found("liga 11912345678") == [("TELEFONE", "11912345678")]


def test_numero_qualquer_de_onze_digitos_nao_e_mascarado():
    assert found("protocolo 12345678900") == []


# ---------------------------------------------------------------- CNPJ
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CNPJ 11.222.333/0001-81", [("CNPJ", "11.222.333/0001-81")]),
        ("cnpj 11222333000181", [("CNPJ", "11222333000181")]),
        ("empresa 12.ABC.345/01DE-35", [("CNPJ", "12.ABC.345/01DE-35")]),
        ("o 11.222.333/0001-80 tá certo?", [("CNPJ", "11.222.333/0001-80")]),
        # Alfanumérico sem formatação: só com o contexto dizendo que é CNPJ.
        ("Emite a nota no CNPJ ABCDEFGHJKLM50", [("CNPJ", "ABCDEFGHJKLM50")]),
        ("código ABCDEFGHJKLM50", []),
    ],
)
def test_cnpj(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


# ---------------------------------------------------------------- telefone
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("me liga no (11) 91234-5678", [("TELEFONE", "(11) 91234-5678")]),
        ("zap +55 11 91234-5678", [("TELEFONE", "+55 11 91234-5678")]),
        ("11 91234-5678", [("TELEFONE", "11 91234-5678")]),
        ("fixo (21) 3456-7890", [("TELEFONE", "(21) 3456-7890")]),
        ("meu cel 91234-5678", [("TELEFONE", "91234-5678")]),
        ("tel: 3456-7890", [("TELEFONE", "3456-7890")]),
        # Formatado como telefone, mesmo com DDD inexistente (erro de digitação): mascara inteiro.
        ("(20) 91234-5678", [("TELEFONE", "(20) 91234-5678")]),
    ],
)
def test_telefone(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "a parcela fica R$ 1.234,56",
        "vigência 2024-2025",
        "crédito de 80000 em 120 meses",
        "protocolo 2091234567",  # só dígitos e DDD inexistente
        "ganhei 3456-7890 pontos",  # 8 dígitos sem contexto de telefone
    ],
)
def test_numeros_que_nao_sao_telefone(text: str):
    assert found(text) == []


# ---------------------------------------------------------------- e-mail, CEP, RG
def test_email():
    assert found("manda pra Ana.Souza+vendas@exemplo.com.br!") == [
        ("EMAIL", "Ana.Souza+vendas@exemplo.com.br")
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CEP 01310-100", [("CEP", "01310-100")]),
        ("meu cep é 01310100", [("CEP", "01310100")]),
        ("fica no 01310-100, centro", [("CEP", "01310-100")]),
        ("código 01310100", []),
    ],
)
def test_cep(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("RG 12.345.678-9", [("RG", "12.345.678-9")]),
        ("meu rg é 123456789", [("RG", "123456789")]),
        ("identidade: 12.345.678-X", [("RG", "12.345.678-X")]),
        ("doc 12.345.678-9", [("RG", "12.345.678-9")]),
        ("rg mg-12.345.678", [("RG", "mg-12.345.678")]),
    ],
)
def test_rg(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


# ---------------------------------------------------------------- PIX e conta
def test_pix_chave_aleatoria():
    key = "123e4567-e89b-42d3-a456-426614174000"
    assert found(f"pode mandar no {key}") == [("PIX", key)]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("chave pix: 529.982.247-25", "529.982.247-25"),
        ("faz um pix pra vendas@exemplo.com", "vendas@exemplo.com"),
        ("meu pix é (11) 91234-5678", "(11) 91234-5678"),
        ("PIX 11.222.333/0001-81", "11.222.333/0001-81"),
        ("Pode fazer o pix direto pra mim que eu repasso: (11) 91234-5678", "(11) 91234-5678"),
    ],
)
def test_documento_usado_como_chave_pix(text: str, value: str):
    assert found(text) == [("PIX", value)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "ag 1234 cc 56789-0",
            [("CONTA_BANCARIA", "1234"), ("CONTA_BANCARIA", "56789-0")],
        ),
        (
            "Agência: 0001, conta corrente 123456-7",
            [("CONTA_BANCARIA", "0001"), ("CONTA_BANCARIA", "123456-7")],
        ),
        ("conta poupança nº 98765-X", [("CONTA_BANCARIA", "98765-X")]),
        ("por conta disso 2 parcelas", []),
        ("na conta 3 vezes", []),
    ],
)
def test_conta_bancaria(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cartão 4111 1111 1111 1111", [("CONTA_BANCARIA", "4111 1111 1111 1111")]),
        ("final 4111-1111-1111-1111 ok", [("CONTA_BANCARIA", "4111-1111-1111-1111")]),
        ("numero 4111111111111111", [("CONTA_BANCARIA", "4111111111111111")]),
        ("4111 1111 1111 1112", []),  # não passa no Luhn
    ],
)
def test_numero_de_cartao_conta_como_dado_bancario(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


# ---------------------------------------------------------------- placa
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("placa ABC1D23", [("PLACA", "ABC1D23")]),
        ("o carro BRA-2019 tá ok", [("PLACA", "BRA-2019")]),
        ("placa abc-1234", [("PLACA", "abc-1234")]),
        ("ano2024 foi bom", []),
        ("versão XYZ1K23", []),  # quinta posição só vai de A a J
    ],
)
def test_placa(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


# ---------------------------------------------------------------- endereço
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("moro na Rua das Flores, 123", [("ENDERECO", "Rua das Flores, 123")]),
        ("Av. Paulista 1000 apto 52", [("ENDERECO", "Av. Paulista 1000 apto 52")]),
        ("rua augusta nº 500 bloco B", [("ENDERECO", "rua augusta nº 500 bloco B")]),
        ("Alameda Santos, n. 45, casa 2", [("ENDERECO", "Alameda Santos, n. 45, casa 2")]),
        ("Endereço: Rua Tiradentes 867, ap 41", [("ENDERECO", "Rua Tiradentes 867, ap 41")]),
        ("meu endereço é Travessa Boa Vista", [("ENDERECO", "Travessa Boa Vista")]),
        ("vou passar na rua amanhã", []),
        ("a avenida tava parada", []),
    ],
)
def test_endereco(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


# ---------------------------------------------------------------- nomes
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Oi, meu nome é Roberto Lima", [("NOME_PESSOA", "Roberto Lima")]),
        ("me chamo Ana Paula de Souza.", [("NOME_PESSOA", "Ana Paula de Souza")]),
        ("posso falar com a Sra. Fernanda?", [("NOME_PESSOA", "Fernanda")]),
        ("aqui é o João Pedro da Consórcio Bom", [("NOME_PESSOA", "João Pedro")]),
        ("meu nome é muito comum", []),
        ("sou a favor", []),
    ],
)
def test_nome_por_contexto(text: str, expected: list[tuple[str, str]]):
    assert found(text) == expected


def test_nomes_conhecidos_dos_participantes():
    text = "Oi roberto, tudo bem? Pode chamar o Roberto Lima ou o Joao."
    spans = detect_known_names(text, ["Roberto Lima", "João Silva", "+55 11 91234-5678"])
    assert [(s.type.value, text[s.start : s.end]) for s in spans] == [
        ("NOME_PESSOA", "roberto"),
        ("NOME_PESSOA", "Roberto Lima"),
        ("NOME_PESSOA", "Joao"),
    ]
    assert {s.source for s in spans} == {"participante"}


def test_nome_conhecido_nao_casa_dentro_de_outra_palavra():
    assert detect_known_names("A robertoteca e o Anarquismo", ["Roberto", "Ana"]) == []


def test_nome_conhecido_ignora_palavras_comuns_e_curtas():
    text = "Bom dia, tudo bem? Eu vou sim."
    assert detect_known_names(text, ["Bom Dia", "Eu", "Loja Sim"]) == []


# ---------------------------------------------------------------- vários tipos juntos
def test_mensagem_com_varios_dados():
    text = (
        "Segue meus dados: CPF 529.982.247-25, email roberto.lima@exemplo.com, "
        "cel (11) 91234-5678, CEP 01310-100."
    )
    assert found(text) == [
        ("CPF", "529.982.247-25"),
        ("EMAIL", "roberto.lima@exemplo.com"),
        ("TELEFONE", "(11) 91234-5678"),
        ("CEP", "01310-100"),
    ]


def test_texto_sem_dado_pessoal():
    assert found("Oi! Quanto fica a parcela do consórcio de 80 mil em 100 meses?") == []
