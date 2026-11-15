"""Avaliação pelo runtime de produção, relatório, model card e plano de publicação (sem PyTorch)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from radar.ml.testing import tiny_classifier_model, tiny_ner_model
from radar_training.evaluate import evaluate_classifier, evaluate_ner
from radar_training.pipeline import evaluate
from radar_training.publish import model_plan


def test_avaliacao_do_ner_compara_modelo_regex_e_os_dois_juntos(tmp_path: Path, tiny_dataset: Path):
    model = tiny_ner_model(tmp_path / "ner")
    result = evaluate_ner(model, tiny_dataset, log=lambda _: None)
    test = result["splits"]["test"]
    assert test["entidades"] == 2
    assert test["modelo"]["exato"]["micro"]["f1"] == 1.0
    assert test["modelo"]["mascara"]["entities_fully_masked"] == 1.0
    assert test["modelo"]["confusao"]["NOME_PESSOA"]["NOME_PESSOA"] == 2
    # Os nomes não estão no cadastro: sozinha, a regex não acha "joana" em "fala com joana".
    assert test["regex"]["mascara"]["entities_fully_masked"] < 1.0
    assert test["regex_e_modelo"]["mascara"]["entities_fully_masked"] == 1.0
    assert "llm_zero_shot" not in test
    # Sem pesos do Transformers na pasta: só a paridade entre os dois ONNX.
    assert result["paridade"] == {"mensagens": 5, "onnx_fp32_x_int8": 1.0}
    assert set(result["latencia"]) == {"int8", "fp32"}


def test_avaliacao_do_classificador_respeita_quem_escreveu(tmp_path: Path, tiny_dataset: Path):
    model = tiny_classifier_model(tmp_path / "classificador")
    result = evaluate_classifier(model, tiny_dataset, log=lambda _: None)
    test = result["splits"]["test"]
    per_class = test["modelo"]["metricas"]["per_class"]
    assert per_class["pagamento_fora_canal"]["f1"] == 1.0
    assert per_class["objecao_preco"]["f1"] == 1.0
    assert test["modelo"]["metricas"]["micro"]["fp"] == 0
    assert "regras" in test
    assert "regras_e_modelo" in test
    assert ("tfidf" in test) == (importlib.util.find_spec("sklearn") is not None)
    assert result["paridade"]["onnx_fp32_x_int8_decisoes"] == 1.0


def test_relatorio_e_model_card_saem_do_mesmo_json(
    tmp_path: Path, tiny_dataset: Path, training_info: dict[str, Any]
):
    folder = tiny_ner_model(tmp_path / "models" / "ner-teste", base_model="base/teste")
    (folder / "training.json").write_text(json.dumps(training_info), encoding="utf-8")
    reports = tmp_path / "reports"
    evaluate(folder, tiny_dataset, reports, namespace="alguem", log=lambda _: None)

    report = (reports / "ner-teste.md").read_text(encoding="utf-8")
    assert "## Resumo" in report
    assert "regex + modelo (o que roda no Radar)" in report
    assert "LLM zero-shot não rodou" in report
    assert "## Matriz de confusão" in report
    assert (
        json.loads((reports / "ner-teste.json").read_text(encoding="utf-8"))["modelo"]["name"]
        == "ner-teste"
    )

    card = (folder / "README.md").read_text(encoding="utf-8")
    assert card.startswith("---\nlanguage:\n- pt\nlicense: apache-2.0")
    assert 'model="alguem/ner-teste"' in card
    assert "alguem/radar-vendas-conversas-sinteticas" in card
    assert "**100.0**" in card  # F1 do modelo no teste
    assert "Base `base/teste` sob licença MIT." in card


def test_plano_de_publicacao_usa_o_id_final_e_exige_os_arquivos_do_runtime(
    tmp_path: Path, tiny_dataset: Path, training_info: dict[str, Any]
):
    folder = tiny_ner_model(tmp_path / "models" / "ner-teste")
    (folder / "training.json").write_text(json.dumps(training_info), encoding="utf-8")
    (folder / "rascunho.txt").write_text("não vai", encoding="utf-8")
    evaluate(
        folder, tiny_dataset, tmp_path / "reports", namespace="SEU_USUARIO", log=lambda _: None
    )

    files = {
        p.relative_to(folder).as_posix()
        for p in model_plan(folder, "outra/ner-teste", dataset_id="outra/ds")
    }
    assert {
        "README.md",
        "radar_model.json",
        "tokenizer.json",
        "onnx/model_quantized.onnx",
        "metrics.json",
    } <= files
    assert "rascunho.txt" not in files
    assert 'model="outra/ner-teste"' in (folder / "README.md").read_text(encoding="utf-8")

    (folder / "tokenizer.json").unlink()
    with pytest.raises(FileNotFoundError, match=r"tokenizer\.json"):
        model_plan(folder, "outra/ner-teste", dataset_id="outra/ds")


# ---------------------------------------------------------------- quantização com conferência
def _fake_quantizer(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Troca o quantizador por uma cópia do fp32 e devolve a lista das receitas pedidas."""
    import shutil

    from radar_training import export

    made: list[str] = []

    def fake(clean: Path, target: Path, **recipe: bool) -> None:
        made.append(target.name)
        shutil.copyfile(clean, target)

    monkeypatch.setattr(export, "_quantize_to", fake)
    return made


def test_quantizacao_fica_com_a_primeira_receita_que_passa_na_validacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from radar_training.export import INT8, QUANT_RECIPES, quantize

    folder = tiny_ner_model(tmp_path / "ner")
    made = _fake_quantizer(monkeypatch)
    scores = {
        "onnx/model.onnx": 0.95,
        "onnx/candidato-0.onnx": 0.64,
        "onnx/candidato-1.onnx": 0.945,
    }

    result = quantize(folder, scores.__getitem__)

    assert made == ["candidato-0.onnx", "candidato-1.onnx"]
    assert result["aprovado"] is True
    assert result["receita"] == QUANT_RECIPES[1][0]
    assert result["metrica_fp32"] == 0.95
    assert result["metrica_quantizado"] == 0.945
    assert [a["metrica"] for a in result["tentativas"]] == [0.64, 0.945]
    assert (folder / INT8).is_file()
    assert not list((folder / "onnx").glob("candidato-*.onnx"))


def test_quantizacao_que_passa_de_primeira_nao_mede_as_outras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from radar_training.export import QUANT_RECIPES, quantize

    folder = tiny_ner_model(tmp_path / "ner")
    made = _fake_quantizer(monkeypatch)

    result = quantize(folder, lambda name: 0.95 if name.endswith("model.onnx") else 0.948)

    assert made == ["candidato-0.onnx"]
    assert result["aprovado"] is True
    assert result["receita"] == QUANT_RECIPES[0][0]


def test_quantizacao_reprovada_avisa_e_guarda_a_menos_ruim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from radar_training.export import QUANT_RECIPES, quantize

    folder = tiny_ner_model(tmp_path / "ner")
    _fake_quantizer(monkeypatch)
    scores = {"onnx/model.onnx": 0.95, "onnx/candidato-0.onnx": 0.70, "onnx/candidato-1.onnx": 0.30}

    result = quantize(folder, scores.__getitem__)

    assert result["aprovado"] is False
    assert result["receita"] == QUANT_RECIPES[0][0]
    assert result["metrica_quantizado"] == 0.70


def test_relatorio_conta_como_foi_a_quantizacao():
    from radar_training.report import quantization_lines

    assert quantization_lines({}) == []
    approved = "\n".join(
        quantization_lines(
            {
                "quantizacao": {
                    "receita": "uint8",
                    "aprovado": True,
                    "tolerancia": 0.01,
                    "metrica_fp32": 0.95,
                    "metrica_quantizado": 0.945,
                    "tentativas": [
                        {"receita": "int8 por canal com faixa reduzida", "metrica": 0.64},
                        {"receita": "uint8", "metrica": 0.945},
                    ],
                }
            }
        )
    )
    assert "**uint8**" in approved
    assert "0.9450" in approved
    assert "int8 por canal com faixa reduzida (0.6400)" in approved
    rejected = "\n".join(
        quantization_lines(
            {
                "quantizacao": {
                    "receita": "uint8",
                    "aprovado": False,
                    "tolerancia": 0.01,
                    "metrica_fp32": 0.95,
                    "metrica_quantizado": 0.7,
                    "tentativas": [{"receita": "uint8", "metrica": 0.7}],
                }
            }
        )
    )
    assert "o manifesto aponta para o fp32" in rejected
