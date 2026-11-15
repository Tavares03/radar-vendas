"""Playbooks em YAML e o motor de regras (inclusive negação e citação)."""

from __future__ import annotations

import pytest

from radar.playbooks import (
    PlaybookError,
    RuleEngine,
    available_playbooks,
    load_playbook,
    parse_playbook,
)
from radar.taxonomy import SenderRole, Severity

V, C = SenderRole.VENDEDOR, SenderRole.CLIENTE


def hits(sector: str, text: str, sender: SenderRole = V) -> list[str]:
    engine = RuleEngine(load_playbook(sector))
    return [hit.type for hit in engine.evaluate_message(text, sender)]


def test_playbooks_iniciais_existem_e_herdam_do_generico():
    assert {"consorcio", "seguros", "imobiliaria", "clinica", "generico"} <= set(
        available_playbooks()
    )
    consorcio = load_playbook("consorcio")
    rule_ids = {rule.id for rule in consorcio.regras}
    assert "pagamento-pix-pessoal" in rule_ids  # veio do genérico
    assert any(rule.tipo == "promessa_indevida" for rule in consorcio.regras)
    assert sum(consorcio.criterios_nota.model_dump().values()) == 100


# ---------------------------------------------------------------- riscos
@pytest.mark.parametrize(
    ("sector", "text"),
    [
        ("consorcio", "Pode ficar tranquilo que sua contemplação é garantida"),
        ("consorcio", "Você vai ser contemplado já no terceiro mês, pode contar"),
        ("consorcio", "Com lance de 30% você é contemplado no primeiro mês com certeza"),
        ("seguros", "Cobre tudo, qualquer coisa que acontecer a seguradora paga"),
        ("seguros", "Sinistro aprovado na hora, garantido"),
        ("imobiliaria", "Aprovação garantida, já conversei com o gerente"),
        ("clinica", "Resultado garantido, fica igualzinho a foto"),
        ("generico", "Entrega garantida em 24h, se atrasar eu pago do meu bolso"),
    ],
)
def test_promessa_indevida(sector: str, text: str):
    assert hits(sector, text) == ["promessa_indevida"]


@pytest.mark.parametrize(
    ("sector", "text"),
    [
        ("consorcio", "Não posso te garantir a contemplação, ela só acontece por sorteio ou lance"),
        (
            "consorcio",
            "Ninguém pode garantir data de contemplação, quem promete isso está mentindo",
        ),
        ("consorcio", "Cuidado: ninguém pode prometer contemplação em 3 meses. Isso é proibido"),
        ("consorcio", "Lance alto aumenta a chance, mas não garante contemplação"),
        ("seguros", "Não vou te dizer que cobre tudo, porque não cobre. Tem franquia e exclusões"),
        ("imobiliaria", "Aprovação garantida não existe, quem decide é o banco"),
        ("clinica", "Ninguém sério promete resultado garantido. Aqui a gente explica antes"),
        ("generico", "Não posso prometer entrega até sexta, mas te passo o rastreio"),
    ],
)
def test_negacao_e_citacao_nao_viram_alerta(sector: str, text: str):
    assert hits(sector, text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Faz a entrada no meu pix pessoal [PIX] que agiliza", "pagamento_fora_canal"),
        (
            "Deposita na minha conta, ag [CONTA_BANCARIA] cc [CONTA_BANCARIA]",
            "pagamento_fora_canal",
        ),
        ("Me paga por fora que eu te dou um desconto", "pagamento_fora_canal"),
        (
            "Me passa a senha do app do seu banco que eu faço tudo por você",
            "dados_pessoais_indevidos",
        ),
        ("Manda foto do cartão frente e verso, com o código de trás", "dados_pessoais_indevidos"),
        ("Essa condição é só hoje, amanhã já não vale mais", "pressao_abusiva"),
        ("É a última vaga, se você não pegar outro pega", "pressao_abusiva"),
        ("Que saco, para de encher", "linguagem_inadequada"),
        ("Porra, já expliquei três vezes", "linguagem_inadequada"),
    ],
)
def test_riscos_genericos(text: str, expected: str):
    assert hits("consorcio", text) == [expected]


def test_pagamento_pelo_canal_oficial_nao_e_risco():
    assert (
        hits(
            "generico",
            "O pagamento é pelo boleto ou link oficial, nunca por conta de pessoa física",
        )
        == []
    )
    assert hits("generico", "Te enviei o link de pagamento oficial, é só seguir os passos") == []


def test_regra_de_vendedor_nao_dispara_em_mensagem_do_cliente():
    assert hits("consorcio", "Contemplação garantida? Vi isso num anúncio", C) == []


def test_severidade_e_explicacao_vem_do_playbook():
    engine = RuleEngine(load_playbook("consorcio"))
    (hit,) = engine.evaluate_message("Contemplação garantida, eu garanto pessoalmente", V)
    assert hit.severity is Severity.CRITICO
    assert "sorteio" in hit.explanation.lower()
    assert "garantida" in hit.evidence.lower()


# ---------------------------------------------------------------- sinais do cliente
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Achei meio caro, viu", ["objecao_preco"]),
        ("Isso não é golpe não né?", ["objecao_confianca"]),
        ("Vou conversar com minha esposa primeiro", ["objecao_vou_pensar"]),
        ("Na Caixa tá mais barato", ["objecao_concorrente"]),
        ("Tem multa se cancelar?", ["objecao_cancelamento"]),
        ("Isso aí demora demais", ["objecao_prazo"]),
        ("Consegue me mandar uma simulação?", ["pedido_cliente"]),
        ("Me envia a proposta em PDF?", ["pedido_cliente"]),
        ("Fechado, vamos fazer", ["sinal_compra"]),
        ("Onde eu assino?", ["sinal_compra"]),
        ("Não achei caro não, o valor tá ok", []),
        ("Não tô vendo com mais ninguém, só com vocês", []),
    ],
)
def test_rotulos_de_mensagens_do_cliente(text: str, expected: list[str]):
    assert hits("consorcio", text, C) == expected


# ---------------------------------------------------------------- divulgações
def test_setores_nao_herdam_divulgacao_de_varejo():
    for sector in ("consorcio", "seguros", "imobiliaria", "clinica"):
        ids = {d.id for d in load_playbook(sector).divulgacoes_obrigatorias}
        assert "condicoes-de-compra" not in ids, sector
    assert "condicoes-de-compra" in {
        d.id for d in load_playbook("generico").divulgacoes_obrigatorias
    }


def test_desativar_tambem_vale_para_divulgacao_herdada():
    playbook = parse_playbook("id: x\nnome: X\nherda: generico\ndesativar: [condicoes-de-compra]\n")
    assert playbook.divulgacoes_obrigatorias == []


def test_divulgacoes_obrigatorias():
    engine = RuleEngine(load_playbook("consorcio"))
    found = engine.disclosures(
        [
            (V, "Importante: tem taxa de administração de 16% diluída nas parcelas"),
            (C, "e o fundo de reserva?"),
            (V, "A contemplação é só por sorteio ou lance"),
        ]
    )
    assert found["taxa-administracao"] == 0
    assert found["sorteio-lance"] == 2
    assert found["fundo-reserva"] is None  # só o cliente falou


# ---------------------------------------------------------------- validação de playbook novo
def test_playbook_proprio_valido_e_heranca():
    playbook = parse_playbook(
        """
id: minha-loja
nome: Minha Loja
herda: generico
regras:
  - id: frete-gratis
    tipo: informacao_enganosa
    descricao: Prometer frete grátis
    termos: ["frete grátis sempre"]
desativar: [pressao-so-hoje]
"""
    )
    engine = RuleEngine(playbook)
    assert [h.type for h in engine.evaluate_message("Aqui é frete grátis sempre!", V)] == [
        "informacao_enganosa"
    ]
    assert engine.evaluate_message("Essa condição é só hoje", V) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "id: x\nnome: X\nregras:\n  - {id: a, tipo: inventado, descricao: d, termos: [x]}",
            "tipo",
        ),
        (
            "id: x\nnome: X\nregras:\n  - {id: a, tipo: promessa_indevida, descricao: d, padroes: ['(']}",
            "regex",
        ),
        ("id: x\nnome: X\ncriterios_nota: {conformidade: 90}", "100"),
        ("id: x\nnome: X\nherda: nao-existe", "nao-existe"),
        ("id: [", "YAML"),
        ("id: x\nnome: X\nregras:\n  - {id: a, tipo: promessa_indevida, descricao: d}", "padr"),
    ],
)
def test_playbook_invalido_explica_o_erro(content: str, message: str):
    with pytest.raises(PlaybookError) as caught:
        parse_playbook(content)
    assert message.lower() in str(caught.value).lower()
