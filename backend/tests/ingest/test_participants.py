"""Identificação de vendedor e cliente."""

from __future__ import annotations

import uuid

import pytest

from radar.ingest.participants import SellerRef, identify_participants, names_match
from radar.ingest.whatsapp import parse_chat
from radar.taxonomy import SenderRole

CARLA = SellerRef(uuid.uuid4(), "Carla Mendes", ("Carla Consórcios", "+55 11 98888-7777"))
DIEGO = SellerRef(uuid.uuid4(), "Diego Ramos")


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("Carla Mendes", "carla mendes", True),
        ("Carla Mendes", "Cárla  Mendes", True),
        ("Carla Mendes", "Carla M. Mendes", True),
        ("Carla Mendes", "Carla", True),
        ("Carla Mendes", "Mendes Carla", False),  # primeiro nome diferente: não arrisca
        ("Carla Mendes", "Karla Mendes", False),
        ("Carla Mendes", "Roberto Lima", False),
        ("+55 11 98888-7777", "11988887777", True),
        ("+55 11 98888-7777", "(11) 8888-7777", True),
        ("+55 11 98888-7777", "+55 11 98888-0000", False),
        ("Ana", "Ana", True),
        ("Ana", "Ana Paula", False),  # nome curto demais para aproximar
        ("", "Carla", False),
    ],
)
def test_names_match(left: str, right: str, expected: bool):
    assert names_match(left, right) is expected


def test_reconhece_vendedor_cadastrado_pelo_nome():
    result = identify_participants(["Roberto Lima", "Carla Mendes"], sellers=[CARLA, DIEGO])
    assert result["Carla Mendes"].role is SenderRole.VENDEDOR
    assert result["Carla Mendes"].seller_id == CARLA.id
    assert result["Carla Mendes"].confidence == "alta"
    assert result["Roberto Lima"].role is SenderRole.CLIENTE
    assert result["Roberto Lima"].confidence == "alta"


def test_reconhece_vendedor_pelo_apelido_ou_telefone():
    by_alias = identify_participants(["Carla Consórcios", "Roberto"], sellers=[CARLA])
    assert by_alias["Carla Consórcios"].seller_id == CARLA.id

    by_phone = identify_participants(["+55 11 98888-7777", "Roberto"], sellers=[CARLA])
    assert by_phone["+55 11 98888-7777"].role is SenderRole.VENDEDOR
    assert by_phone["Roberto"].role is SenderRole.CLIENTE


def test_nome_informado_no_envio_tem_prioridade():
    result = identify_participants(
        ["Bia Souza", "Roberto Lima"], sellers=[CARLA], seller_hint="bia souza"
    )
    assert result["Bia Souza"].role is SenderRole.VENDEDOR
    assert result["Bia Souza"].seller_id is None  # ainda não cadastrada
    assert result["Roberto Lima"].role is SenderRole.CLIENTE


def test_vendedor_escolhido_no_envio_mesmo_sem_o_nome_bater():
    chat = parse_chat(
        "10/01/2024 09:00 - Roberto Lima: Oi, quanto custa o plano?\n"
        "10/01/2024 09:01 - Atendimento Loja: Olá! Posso te ajudar. Segue a tabela\n"
    )
    result = identify_participants(
        chat.authors,
        sellers=[CARLA, DIEGO],
        forced_seller=DIEGO,
        chat_title="Roberto Lima",
        messages=chat.content_messages,
    )
    assert result["Atendimento Loja"].role is SenderRole.VENDEDOR
    assert result["Atendimento Loja"].seller_id == DIEGO.id
    assert result["Roberto Lima"].role is SenderRole.CLIENTE


def test_titulo_do_export_aponta_o_cliente():
    result = identify_participants(
        ["Roberto Lima", "Fulana"], chat_title="Roberto Lima", sellers=[]
    )
    assert result["Fulana"].role is SenderRole.VENDEDOR
    assert result["Fulana"].confidence == "media"
    assert result["Roberto Lima"].role is SenderRole.CLIENTE
    assert result["Roberto Lima"].confidence == "media"


def test_conteudo_indica_quem_vende():
    chat = parse_chat(
        "10/01/2024 09:00 - A: Bom dia! Aqui é a Bia da Casa Nova. Em que posso ajudar?\n"
        "10/01/2024 09:01 - B: Queria saber quanto custa o apartamento\n"
        "10/01/2024 09:02 - A: Temos opções a partir de 300 mil. Segue a tabela\n"
        "10/01/2024 09:03 - B: Tá caro, vou pensar\n"
    )
    result = identify_participants(chat.authors, messages=chat.content_messages)
    assert result["A"].role is SenderRole.VENDEDOR
    assert result["A"].confidence == "media"
    assert result["B"].role is SenderRole.CLIENTE


def test_sem_pistas_assume_que_o_cliente_falou_primeiro_e_avisa():
    chat = parse_chat("10/01/2024 09:00 - A: oi\n10/01/2024 09:01 - B: olá\n")
    result = identify_participants(chat.authors, messages=chat.content_messages)
    assert result["A"].role is SenderRole.CLIENTE
    assert result["B"].role is SenderRole.VENDEDOR
    assert result["B"].confidence == "baixa"
    assert result["A"].confidence == "baixa"


def test_grupo_com_dois_clientes():
    result = identify_participants(["Carla Mendes", "Roberto Lima", "Sônia Lima"], sellers=[CARLA])
    roles = {author: info.role for author, info in result.items()}
    assert roles == {
        "Carla Mendes": SenderRole.VENDEDOR,
        "Roberto Lima": SenderRole.CLIENTE,
        "Sônia Lima": SenderRole.CLIENTE,
    }


def test_conversa_de_uma_pessoa_so():
    result = identify_participants(["Roberto Lima"], sellers=[CARLA])
    assert result["Roberto Lima"].role is SenderRole.VENDEDOR
    assert result["Roberto Lima"].confidence == "baixa"


def test_sem_autores():
    assert identify_participants([]) == {}
