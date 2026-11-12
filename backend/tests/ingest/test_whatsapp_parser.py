"""Parser do export do WhatsApp: um caso por formato e por armadilha conhecida.

Todas as conversas aqui são inventadas.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from radar.ingest.whatsapp import ParseError, chat_title_from_filename, parse_chat
from radar.taxonomy import MessageKind

LRM = "‎"
NNBSP = " "

ANDROID_PT = f"""25/12/2023 14:32 - As mensagens e ligações são protegidas com a criptografia de ponta a ponta. Somente as pessoas nesta conversa podem ler, ouvir ou compartilhar. Saiba mais
25/12/2023 14:32 - Carla Mendes: Bom dia, Roberto! Tudo bem?
25/12/2023 14:33 - Roberto Lima: Bom dia. Queria saber do consórcio de imóvel
25/12/2023 14:35 - Carla Mendes: Claro! Temos três opções:
1) carta de 200 mil
2) carta de 300 mil

Qual faixa te interessa?
25/12/2023 14:40 - Roberto Lima: <Mídia oculta>
25/12/2023 14:41 - Roberto Lima: {LRM}PTT-20231225-WA0003.opus (arquivo anexado)
25/12/2023 14:42 - Carla Mendes: {LRM}IMG-20231225-WA0004.jpg (arquivo anexado)
Segue a tabela atualizada
25/12/2023 14:43 - Roberto Lima: Mensagem apagada
25/12/2023 14:44 - Carla Mendes: A parcela fica em R$ 1.250,00 <Mensagem editada>
25/12/2023 14:45 - Roberto Lima: null
"""

IOS_PT = f"""[25/12/2023, 14:32:15] Carla Mendes: {LRM}As mensagens e ligações são protegidas com a criptografia de ponta a ponta.
[25/12/2023, 14:32:20] Carla Mendes: Bom dia, Roberto!
[25/12/2023, 14:33:01] Roberto Lima: Bom dia. Queria saber do consórcio
[25/12/2023, 14:34:10] Roberto Lima: {LRM}áudio ocultado
{LRM}[25/12/2023, 14:35:42] Roberto Lima: {LRM}<anexado: 00000012-AUDIO-2023-12-25-14-35-42.opus>
[25/12/2023, 14:36:00] Carla Mendes: Proposta.pdf • {LRM}3 páginas {LRM}<anexado: 00000013-Proposta.pdf>
[25/12/2023, 14:37:00] Roberto Lima: {LRM}imagem ocultada
[25/12/2023, 14:38:00] Roberto Lima: {LRM}Esta mensagem foi apagada.
[25/12/2023, 14:39:00] Carla Mendes: Combinado: te ligo amanhã {LRM}<Mensagem editada>
"""

ANDROID_EN = f"""12/25/23, 2:32{NNBSP}PM - Messages and calls are end-to-end encrypted. Only people in this chat can read, listen to, or share them. Learn more
12/25/23, 2:32{NNBSP}PM - Carla Mendes: Good morning!
12/25/23, 2:33{NNBSP}PM - Roberto Lima: <Media omitted>
12/25/23, 11:59{NNBSP}PM - Carla Mendes: IMG-20231225-WA0001.jpg (file attached)
12/26/23, 12:05{NNBSP}AM - Roberto Lima: This message was deleted
12/26/23, 12:30{NNBSP}PM - Roberto Lima: Thanks <This message was edited>
"""

IOS_EN = f"""[12/25/23, 2:32:15{NNBSP}PM] Carla Mendes: Good morning
[12/25/23, 2:33:00{NNBSP}PM] Roberto Lima: {LRM}image omitted
[12/25/23, 2:34:00{NNBSP}PM] Roberto Lima: {LRM}<attached: 00000002-AUDIO-2023-12-25-14-34-00.m4a>
"""


def test_android_pt_br_completo():
    chat = parse_chat(ANDROID_PT)

    assert chat.platform == "android"
    assert chat.date_order == "dmy"
    assert not chat.date_order_ambiguous
    assert chat.authors == ["Carla Mendes", "Roberto Lima"]

    system, greeting, question, multiline, hidden, audio, image, deleted, edited, null = (
        chat.messages
    )
    assert system.kind is MessageKind.SISTEMA
    assert system.author is None
    assert greeting.timestamp == datetime(2023, 12, 25, 14, 32)
    assert greeting.text == "Bom dia, Roberto! Tudo bem?"
    assert question.author == "Roberto Lima"

    assert multiline.text == (
        "Claro! Temos três opções:\n1) carta de 200 mil\n2) carta de 300 mil\n\n"
        "Qual faixa te interessa?"
    )

    assert hidden.kind is MessageKind.OUTRO
    assert hidden.text == ""

    assert audio.kind is MessageKind.AUDIO
    assert audio.attachment == "PTT-20231225-WA0003.opus"
    assert audio.text == ""

    assert image.kind is MessageKind.IMAGEM
    assert image.attachment == "IMG-20231225-WA0004.jpg"
    assert image.text == "Segue a tabela atualizada"

    assert deleted.kind is MessageKind.APAGADA
    assert deleted.text == ""

    assert edited.edited is True
    assert edited.text == "A parcela fica em R$ 1.250,00"

    assert null.kind is MessageKind.OUTRO
    assert null.text == ""


def test_ios_pt_br_completo():
    chat = parse_chat(IOS_PT)

    assert chat.platform == "ios"
    assert chat.date_order == "dmy"
    kinds = [m.kind for m in chat.messages]
    assert kinds == [
        MessageKind.SISTEMA,
        MessageKind.TEXTO,
        MessageKind.TEXTO,
        MessageKind.AUDIO,
        MessageKind.AUDIO,
        MessageKind.DOCUMENTO,
        MessageKind.IMAGEM,
        MessageKind.APAGADA,
        MessageKind.TEXTO,
    ]
    assert chat.messages[1].timestamp == datetime(2023, 12, 25, 14, 32, 20)
    assert chat.messages[4].attachment == "00000012-AUDIO-2023-12-25-14-35-42.opus"
    assert chat.messages[5].attachment == "00000013-Proposta.pdf"
    assert chat.messages[5].text == "Proposta.pdf • 3 páginas"
    assert chat.messages[8].text == "Combinado: te ligo amanhã"
    assert chat.messages[8].edited is True
    assert chat.authors == ["Carla Mendes", "Roberto Lima"]
    # O aviso de criptografia vem "assinado" por um participante no iOS, mas não é conteúdo.
    assert all(m.kind is not MessageKind.SISTEMA for m in chat.content_messages)


def test_android_ingles_am_pm_e_virada_do_dia():
    chat = parse_chat(ANDROID_EN)

    assert chat.platform == "android"
    assert chat.date_order == "mdy"
    assert not chat.date_order_ambiguous
    stamps = [m.timestamp for m in chat.messages]
    assert stamps[1] == datetime(2023, 12, 25, 14, 32)
    assert stamps[3] == datetime(2023, 12, 25, 23, 59)
    assert stamps[4] == datetime(2023, 12, 26, 0, 5)  # 12:05 AM é meia-noite e cinco
    assert stamps[5] == datetime(2023, 12, 26, 12, 30)  # 12:30 PM é meio-dia e meia
    assert chat.messages[2].kind is MessageKind.OUTRO
    assert chat.messages[3].kind is MessageKind.IMAGEM
    assert chat.messages[4].kind is MessageKind.APAGADA
    assert chat.messages[5].text == "Thanks"
    assert chat.messages[5].edited


def test_ios_ingles():
    chat = parse_chat(IOS_EN)

    assert chat.platform == "ios"
    assert chat.date_order == "mdy"
    assert chat.messages[0].timestamp == datetime(2023, 12, 25, 14, 32, 15)
    assert chat.messages[1].kind is MessageKind.IMAGEM
    assert chat.messages[2].kind is MessageKind.AUDIO
    assert chat.messages[2].attachment.endswith(".m4a")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("25/12/23, 14:32 - Carla: oi", datetime(2023, 12, 25, 14, 32)),
        ("25.12.2023, 14:32 - Carla: oi", datetime(2023, 12, 25, 14, 32)),
        ("25-12-2023 14:32 - Carla: oi", datetime(2023, 12, 25, 14, 32)),
        ("2023-12-25, 14:32 - Carla: oi", datetime(2023, 12, 25, 14, 32)),
        ("[25/12/2023 14:32:07] Carla: oi", datetime(2023, 12, 25, 14, 32, 7)),
        ("[2023-12-25, 2:32:07 p.m.] Carla: oi", datetime(2023, 12, 25, 14, 32, 7)),
        ("25/12/2023 14.32 - Carla: oi", datetime(2023, 12, 25, 14, 32)),
    ],
)
def test_variacoes_de_data_e_hora(line: str, expected: datetime):
    chat = parse_chat(line)
    assert chat.messages[0].timestamp == expected
    assert chat.messages[0].author == "Carla"
    assert chat.messages[0].text == "oi"


class TestOrdemDiaMes:
    def test_dia_maior_que_12_decide_dia_mes(self):
        chat = parse_chat("03/04/2024 10:00 - Ana: a\n13/04/2024 10:00 - Ana: b\n")
        assert chat.date_order == "dmy"
        assert not chat.date_order_ambiguous
        assert chat.messages[0].timestamp == datetime(2024, 4, 3, 10, 0)

    def test_segundo_campo_maior_que_12_decide_mes_dia(self):
        chat = parse_chat("04/03/2024 10:00 - Ana: a\n04/13/2024 10:00 - Ana: b\n")
        assert chat.date_order == "mdy"
        assert chat.messages[0].timestamp == datetime(2024, 4, 3, 10, 0)

    def test_ordem_cronologica_desempata(self):
        # Como mês/dia, isto iria de 2 de janeiro a 1 de fevereiro e voltaria: 01/02 → 02/01?
        # Lido como dia/mês: 31/01 não aparece, mas a sequência 01/02, 02/02, 03/02 anda 2 dias;
        # lida como mês/dia andaria 2 meses. A leitura de menor amplitude vence.
        text = "01/02/2024 09:00 - Ana: a\n02/02/2024 09:00 - Ana: b\n03/02/2024 09:00 - Ana: c\n"
        chat = parse_chat(text)
        assert chat.date_order == "dmy"
        assert not chat.date_order_ambiguous
        assert chat.messages[-1].timestamp == datetime(2024, 2, 3, 9, 0)

    def test_inversao_de_ordem_desempata_a_favor_de_mes_dia(self):
        # 1/12 → 2/1 lido como dia/mês voltaria de dezembro para janeiro do mesmo ano.
        text = "1/12/24, 9:00 AM - Ana: a\n2/1/24, 9:00 AM - Ana: b\n"
        chat = parse_chat(text)
        assert chat.date_order == "mdy"
        assert chat.messages[0].timestamp == datetime(2024, 1, 12, 9, 0)
        assert chat.messages[1].timestamp == datetime(2024, 2, 1, 9, 0)

    def test_ambiguidade_real_assume_padrao_brasileiro_e_avisa(self):
        chat = parse_chat("03/04/2024 10:00 - Ana: a\n03/04/2024 10:05 - Bia: b\n")
        assert chat.date_order == "dmy"
        assert chat.date_order_ambiguous
        assert any("dia/mês" in warning for warning in chat.warnings)
        assert chat.messages[0].timestamp == datetime(2024, 4, 3, 10, 0)

    def test_ambiguidade_com_am_pm_assume_padrao_americano(self):
        chat = parse_chat("3/4/24, 10:00 AM - Ana: a\n3/4/24, 10:05 AM - Bia: b\n")
        assert chat.date_order == "mdy"
        assert chat.date_order_ambiguous
        assert chat.messages[0].timestamp == datetime(2024, 3, 4, 10, 0)

    def test_dia_igual_ao_mes_nao_e_ambiguo(self):
        chat = parse_chat("05/05/2024 10:00 - Ana: a\n")
        assert not chat.date_order_ambiguous
        assert chat.messages[0].timestamp == datetime(2024, 5, 5, 10, 0)


def test_mensagem_real_com_palavra_de_sistema_nao_e_descartada():
    text = (
        "10/01/2024 09:00 - Carla Mendes: o banco adicionou uma taxa de 2% este mês\n"
        "10/01/2024 09:01 - Roberto Lima: e a administradora mudou o prazo?\n"
        "10/01/2024 09:02 - Carla Mendes: o outro cliente saiu\n"
    )
    chat = parse_chat(text)
    assert [m.kind for m in chat.messages] == [MessageKind.TEXTO] * 3
    assert [m.author for m in chat.messages] == ["Carla Mendes", "Roberto Lima", "Carla Mendes"]


def test_avisos_de_grupo_sao_sistema():
    text = (
        '10/01/2024 09:00 - Carla Mendes criou o grupo "Consórcio Família"\n'
        "10/01/2024 09:00 - Carla Mendes adicionou Roberto Lima\n"
        "10/01/2024 09:01 - Roberto Lima: oi\n"
        "10/01/2024 09:05 - Roberto Lima saiu\n"
        "10/01/2024 09:06 - Chamada de voz perdida\n"
    )
    chat = parse_chat(text)
    assert [m.kind for m in chat.messages] == [
        MessageKind.SISTEMA,
        MessageKind.SISTEMA,
        MessageKind.TEXTO,
        MessageKind.SISTEMA,
        MessageKind.SISTEMA,
    ]
    assert chat.authors == ["Roberto Lima"]


def test_autor_por_telefone_e_contato_nao_salvo():
    text = (
        "10/01/2024 09:00 - +55 11 91234-5678: Olá, vi o anúncio\n"
        f"[10/01/2024, 09:01:00] ~{NNBSP}Bia Souza: oi\n"
    )
    chat = parse_chat(text)
    assert chat.messages[0].author == "+55 11 91234-5678"
    # A segunda linha tem formato de iOS num arquivo Android: é continuação, não mensagem nova.
    assert len(chat.messages) == 1

    ios = parse_chat(f"[10/01/2024, 09:01:00] ~{NNBSP}Bia Souza: oi\n")
    assert ios.messages[0].author == "Bia Souza"


def test_texto_colado_com_dois_pontos_nao_vira_autor():
    text = (
        "10/01/2024 09:00 - Carla Mendes: Segue o resumo\n"
        "Valor: R$ 200.000,00\n"
        "Prazo: 180 meses\n"
        "10/01/2024 09:01 - Roberto Lima: ok: entendi\n"
    )
    chat = parse_chat(text)
    assert len(chat.messages) == 2
    assert chat.messages[0].text == "Segue o resumo\nValor: R$ 200.000,00\nPrazo: 180 meses"
    assert chat.messages[1].author == "Roberto Lima"
    assert chat.messages[1].text == "ok: entendi"


def test_linha_com_cara_de_cabecalho_e_data_impossivel_e_continuacao():
    text = (
        "10/01/2024 09:00 - Carla Mendes: Datas disponíveis:\n"
        "31/02/2024 10:00 - não existe\n"
        "10/01/2024 09:01 - Roberto Lima: ok\n"
    )
    chat = parse_chat(text)
    assert len(chat.messages) == 2
    assert "31/02/2024" not in chat.messages[1].text
    assert chat.warnings


def test_quebra_de_linha_windows_e_bom():
    text = "﻿10/01/2024 09:00 - Ana: linha 1\r\nlinha 2\r\n10/01/2024 09:01 - Bia: ok\r\n"
    chat = parse_chat(text)
    assert chat.messages[0].text == "linha 1\nlinha 2"
    assert chat.messages[1].text == "ok"


def test_localizacao_contato_e_figurinha():
    text = (
        "10/01/2024 09:00 - Ana: localização: https://maps.google.com/?q=-23.5,-46.6\n"
        "10/01/2024 09:01 - Ana: Bia Souza.vcf (arquivo anexado)\n"
        "10/01/2024 09:02 - Ana: STK-20240110-WA0001.webp (arquivo anexado)\n"
        "10/01/2024 09:03 - Ana: VID-20240110-WA0002.mp4 (arquivo anexado)\n"
    )
    chat = parse_chat(text)
    assert [m.kind for m in chat.messages] == [
        MessageKind.LOCALIZACAO,
        MessageKind.CONTATO,
        MessageKind.FIGURINHA,
        MessageKind.VIDEO,
    ]


def test_limite_de_mensagens_fica_com_as_mais_recentes():
    lines = [f"10/01/2024 09:{i:02d} - Ana: mensagem {i}" for i in range(30)]
    chat = parse_chat("\n".join(lines), max_messages=10)
    assert len(chat.messages) == 10
    assert chat.truncated == 20
    assert chat.messages[0].text == "mensagem 20"
    assert [m.index for m in chat.messages] == list(range(10))
    assert any("mais antigas" in w for w in chat.warnings)


@pytest.mark.parametrize(
    "text",
    ["", "isto não é um export", "Carla: oi\nRoberto: olá", '{"json": true}'],
)
def test_arquivo_que_nao_e_export_e_recusado(text: str):
    with pytest.raises(ParseError):
        parse_chat(text)


def test_so_avisos_de_sistema_e_recusado():
    with pytest.raises(ParseError):
        parse_chat("10/01/2024 09:00 - Chamada de voz perdida\n")


@pytest.mark.parametrize(
    ("filename", "title"),
    [
        ("Conversa do WhatsApp com Roberto Lima.txt", "Roberto Lima"),
        ("Conversa do WhatsApp com Roberto Lima (2).zip", "Roberto Lima"),
        ("WhatsApp Chat with Roberto Lima.txt", "Roberto Lima"),
        ("WhatsApp Chat - Roberto Lima.zip", "Roberto Lima"),
        ("pasta/Conversa do WhatsApp com +55 11 91234-5678.txt", "+55 11 91234-5678"),
        ("_chat.txt", None),
        ("relatorio.txt", None),
    ],
)
def test_titulo_pelo_nome_do_arquivo(filename: str, title: str | None):
    assert chat_title_from_filename(filename) == title
