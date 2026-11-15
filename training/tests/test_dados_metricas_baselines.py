"""Dados, métricas e baselines do treino (sem PyTorch: é assim que a CI roda)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from radar.llm.router import StructuredResult
from radar.taxonomy import PII_TYPES, SenderRole
from radar_training.baselines import (
    llm_classifier,
    llm_ner,
    locate,
    regex_ner,
    rules_classifier,
)
from radar_training.dataset import MessageExample, load_messages, load_ner, masked_text
from radar_training.metrics import (
    DISABLED_THRESHOLD,
    apply_thresholds,
    is_disabled,
    label_confusion,
    mask_coverage,
    multilabel_report,
    ner_confusion,
    span_report,
    tune_thresholds,
)


# ---------------------------------------------------------------- dataset
def write_split(root: Path, split: str, rows: list[dict[str, Any]]) -> None:
    for folder in ("messages", "ner"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    with (
        (root / "messages" / f"{split}.jsonl").open("w", encoding="utf-8") as m,
        (root / "ner" / f"{split}.jsonl").open("w", encoding="utf-8") as n,
    ):
        for row in rows:
            m.write(json.dumps({k: v for k, v in row.items() if k != "entities"}) + "\n")
            n.write(json.dumps({k: row[k] for k in ("id", "text", "sector", "entities")}) + "\n")


ROWS = [
    {
        "id": "t-0#0", "conversation_id": "t-0", "sender": "cliente", "sector": "consorcio",
        "text": "Meu CPF é 529.982.247-25, achei caro", "labels": ["objecao_preco", "rotulo_velho"],
        "entities": [{"type": "CPF", "start": 10, "end": 24}],
    },
    {
        "id": "t-0#1", "conversation_id": "t-0", "sender": "vendedor", "sector": "consorcio",
        "text": "Contemplação garantida no primeiro mês!", "labels": ["promessa_indevida"], "entities": [],
    },
]  # fmt: skip


def test_mensagens_do_classificador_vem_mascaradas_e_so_com_rotulos_conhecidos(tmp_path: Path):
    write_split(tmp_path, "train", ROWS)
    [first, second] = load_messages(tmp_path, "train")
    assert first.text == "Meu CPF é [CPF], achei caro"
    assert first.labels == {"objecao_preco"}
    assert first.sender is SenderRole.CLIENTE
    assert second.labels == {"promessa_indevida"}
    [ner, _] = load_ner(tmp_path, "train")
    assert ner.entities == (("CPF", 10, 24),)


def test_textos_desalinhados_entre_pastas_sao_erro(tmp_path: Path):
    write_split(tmp_path, "train", ROWS)
    lines = (tmp_path / "ner" / "train.jsonl").read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("achei caro", "achei barato")
    (tmp_path / "ner" / "train.jsonl").write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ValueError, match="texto diferente"):
        load_messages(tmp_path, "train")


def test_mascara_por_entidade_anotada():
    assert masked_text("ligue 11 98888-7777", (("TELEFONE", 6, 19),)) == "ligue [TELEFONE]"


# ---------------------------------------------------------------- métricas de NER
def test_acerto_exato_exige_tipo_e_fronteiras():
    gold = [[("CPF", 0, 14), ("NOME_PESSOA", 20, 25)]]
    predicted = [[("CPF", 0, 14), ("NOME_PESSOA", 20, 24), ("EMAIL", 30, 40)]]
    report = span_report(gold, predicted, PII_TYPES)
    assert (report.per_class["CPF"].tp, report.per_class["CPF"].fp) == (1, 0)
    assert (report.per_class["NOME_PESSOA"].tp, report.per_class["NOME_PESSOA"].fn) == (0, 1)
    assert report.per_class["EMAIL"].fp == 1
    assert report.micro.tp == 1
    assert report.micro.precision == pytest.approx(1 / 3)
    assert report.micro.recall == pytest.approx(1 / 2)


def test_cobertura_da_mascara_ignora_o_tipo_mas_exige_a_entidade_inteira():
    gold = [[("PIX", 0, 10), ("NOME_PESSOA", 20, 25)]]
    # O PIX ficou mascarado como TELEFONE (protegido); o nome só pela metade (exposto).
    predicted = [[("TELEFONE", 0, 10), ("NOME_PESSOA", 20, 22)]]
    coverage = mask_coverage(gold, predicted, PII_TYPES)
    assert coverage["entities_fully_masked"] == 0.5
    assert coverage["per_type"]["PIX"] == 1.0  # type: ignore[index]
    assert coverage["per_type"]["NOME_PESSOA"] == 0.0  # type: ignore[index]
    assert coverage["char_precision"] == 1.0


def test_matriz_de_confusao_do_ner():
    gold = [[("PIX", 0, 10), ("CPF", 12, 26)]]
    predicted = [[("TELEFONE", 0, 10), ("EMAIL", 40, 50)]]
    matrix = ner_confusion(gold, predicted, PII_TYPES)
    assert matrix["PIX"]["TELEFONE"] == 1
    assert matrix["CPF"]["nenhum"] == 1
    assert matrix["nenhum"]["EMAIL"] == 1


# ---------------------------------------------------------------- métricas do classificador
LABELS = ["objecao_preco", "sinal_compra", "promessa_indevida"]


def test_relatorio_multirrotulo_e_matriz():
    gold = [{"objecao_preco"}, {"sinal_compra"}, set()]
    predicted = [{"objecao_preco"}, {"objecao_preco"}, {"promessa_indevida"}]
    report = multilabel_report(gold, predicted, LABELS)
    assert report.per_class["objecao_preco"].as_dict()["precision"] == 0.5
    assert report.per_class["sinal_compra"].recall == 0
    assert report.macro_f1 == pytest.approx((2 / 3 + 0) / 2)  # promessa não tem exemplo verdadeiro
    matrix = label_confusion(gold, predicted, LABELS)
    assert matrix["objecao_preco"]["objecao_preco"] == 1
    assert matrix["sinal_compra"]["objecao_preco"] == 1
    assert matrix["nenhum"]["promessa_indevida"] == 1


def test_limiar_escolhido_maximiza_o_f1_na_validacao():
    gold = [{"objecao_preco"}, {"objecao_preco"}, set(), set()]
    probabilities = np.array(
        [[0.9, 0.1, 0.1], [0.37, 0.1, 0.1], [0.32, 0.1, 0.1], [0.05, 0.1, 0.1]], dtype=np.float32
    )
    thresholds = tune_thresholds(gold, probabilities, LABELS)
    assert thresholds["objecao_preco"] == pytest.approx(0.35)
    assert thresholds["sinal_compra"] == 0.5  # sem exemplos: padrão
    assert apply_thresholds(probabilities, LABELS, thresholds) == [
        {"objecao_preco"},
        {"objecao_preco"},
        set(),
        set(),
    ]


def test_piso_de_precisao_sobe_o_limiar_ou_desliga_o_rotulo():
    # objecao_preco: o limiar de melhor F1 pega os dois verdadeiros e um falso (precisão 2/3);
    # sinal_compra: o modelo erra mais do que acerta em qualquer limiar.
    gold = [{"objecao_preco"}, {"objecao_preco"}, set(), {"sinal_compra"}, set()]
    probabilities = np.array(
        [
            [0.9, 0.2, 0.1],
            [0.3, 0.9, 0.1],
            [0.4, 0.9, 0.1],
            [0.05, 0.6, 0.1],
            [0.05, 0.9, 0.1],
        ],
        dtype=np.float32,
    )
    free = tune_thresholds(gold, probabilities, LABELS)
    assert free["objecao_preco"] == pytest.approx(0.3)  # F1 máximo, aceitando o falso positivo
    assert not is_disabled(free["sinal_compra"])

    strict = tune_thresholds(gold, probabilities, LABELS, min_precision=0.9)
    assert strict["objecao_preco"] == pytest.approx(0.5)  # sobe até não errar, mesmo perdendo um
    assert strict["sinal_compra"] == DISABLED_THRESHOLD
    assert is_disabled(strict["sinal_compra"])
    assert strict["promessa_indevida"] == 0.5  # sem exemplos na validação: padrão
    decided = apply_thresholds(probabilities, LABELS, strict)
    assert all("sinal_compra" not in labels for labels in decided)
    assert decided[:3] == [{"objecao_preco"}, set(), set()]


# ---------------------------------------------------------------- baselines
def test_baseline_de_regex_e_o_detector_de_producao():
    [found] = regex_ner(["meu cpf é 529.982.247-25"])
    assert found == [("CPF", 10, 24)]


def test_baseline_de_regras_usa_o_playbook_do_setor():
    examples = [
        MessageExample("a", "c", SenderRole.VENDEDOR, "Contemplação garantida no primeiro mês!", frozenset(), "consorcio"),
        MessageExample("b", "c", SenderRole.CLIENTE, "Contemplação garantida no primeiro mês!", frozenset(), "consorcio"),
    ]  # fmt: skip
    first, second = rules_classifier(examples)
    assert "promessa_indevida" in first
    assert "promessa_indevida" not in second  # risco só vale para o vendedor


def test_localiza_trechos_do_llm_e_descarta_o_que_nao_esta_no_texto():
    assert locate("pix: ana@x.com", [("PIX", "ana@x.com"), ("CPF", "000"), ("EMAIL", " ")]) == [
        ("PIX", 5, 14)
    ]


class FakeRouter:
    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    def complete_json(self, *, system: str, user: str, schema: Any) -> StructuredResult[Any]:
        self.prompts.append(user)
        return StructuredResult(schema.model_validate(self.answers.pop(0)), "falso", "falso", 1, 1)


def test_classificador_zero_shot_em_lotes_e_so_com_rotulos_validos():
    examples = [
        MessageExample(str(i), "c", SenderRole.CLIENTE, f"msg {i}", frozenset(), "generico")
        for i in range(3)
    ]
    router = FakeRouter(
        [
            {
                "messages": [
                    {"id": 0, "labels": ["objecao_preco", "inventado"]},
                    {"id": 9, "labels": ["x"]},
                ]
            },
            {"messages": [{"id": 0, "labels": ["sinal_compra"]}]},
        ]
    )
    result = llm_classifier(examples, router, batch_size=2)  # type: ignore[arg-type]
    assert result == [{"objecao_preco"}, set(), {"sinal_compra"}]
    assert router.prompts[0] == "0. [cliente] msg 0\n1. [cliente] msg 1"


def test_ner_zero_shot_devolve_posicoes():
    router = FakeRouter(
        [
            {
                "messages": [
                    {
                        "id": 0,
                        "entities": [
                            {"type": "EMAIL", "text": "a@b.com"},
                            {"type": "SENHA", "text": "x"},
                        ],
                    }
                ]
            }
        ]
    )
    assert llm_ner(["mande para a@b.com"], router) == [[("EMAIL", 11, 18)]]  # type: ignore[arg-type]


def test_tfidf_aprende_o_basico():
    pytest.importorskip("sklearn")
    from radar_training.baselines import TfidfBaseline

    def ex(text: str, labels: set[str]) -> MessageExample:
        return MessageExample(text, "c", SenderRole.CLIENTE, text, frozenset(labels), "generico")

    train = [ex(f"achei caro demais {i}", {"objecao_preco"}) for i in range(10)]
    train += [ex(f"bom dia tudo bem {i}", set()) for i in range(10)]
    model = TfidfBaseline().fit(train)
    probabilities = model.predict_proba([ex("muito caro", set()), ex("bom dia", set())])
    column = model.labels.index("objecao_preco")
    assert probabilities[0, column] > probabilities[1, column]
