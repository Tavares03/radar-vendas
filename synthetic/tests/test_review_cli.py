"""Revisão por amostragem, pacote para o Hugging Face e a CLI ``radar-synth``."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from radar_synth.cli import app
from radar_synth.dataset import build_dataset, write_dataset
from radar_synth.hf import build_hf_folder
from radar_synth.review import select_review_sample, write_review

SIZES = {"train": 30, "validation": 10, "test": 10}


def test_amostra_de_revisao_cobre_setores_e_rotulos():
    conversations = build_dataset(sizes=SIZES, seed=5)
    sample = select_review_sample(conversations, n=12, seed=1)
    assert len(sample) == 12
    assert len({c.sector for c in sample}) == 5
    labels = {label for c in sample for m in c.messages for label in m.labels}
    assert {"pedido_cliente", "objecao_preco"} <= labels
    assert select_review_sample(conversations, n=12, seed=1) == sample


def test_arquivos_de_revisao(tmp_path: Path):
    sample = select_review_sample(build_dataset(sizes=SIZES, seed=5), n=5, seed=2)
    markdown, sheet = write_review(sample, tmp_path)
    text = markdown.read_text(encoding="utf-8")
    assert "## " in text
    assert "Alertas esperados" in text
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert len(rows) == sum(len(c.messages) for c in sample)
    assert {"conversa", "mensagem", "texto", "rotulos", "dados_pessoais", "ok", "correcao"} <= set(
        rows[0]
    )


def test_pacote_hugging_face(tmp_path: Path):
    dataset_dir = tmp_path / "dataset"
    write_dataset(build_dataset(sizes=SIZES, seed=6), dataset_dir, seed=6)
    folder = build_hf_folder(dataset_dir, tmp_path / "hf")

    card = (folder / "README.md").read_text(encoding="utf-8")
    assert card.startswith("---\n")
    assert "license: cc-by-4.0" in card
    assert "config_name: ner" in card
    assert "sintétic" in card.lower()
    assert "Limitações" in card
    for config in ("conversations", "messages", "ner"):
        for split in ("train", "validation", "test"):
            assert (folder / config / f"{split}.jsonl").exists()
    assert (folder / "desafio" / "test.jsonl").exists()


def test_cli_gera_dataset_e_amostra(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "generate",
            "--out",
            str(tmp_path),
            "--train",
            "10",
            "--validation",
            "5",
            "--test",
            "5",
            "--exports",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    (version_dir,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["conversations"]["train"] == 10
    assert (version_dir / "conversations" / "desafio.jsonl").exists()

    sample = runner.invoke(
        app, ["sample", "--sector", "seguros", "--seed", "3", "--out", str(tmp_path / "s.zip")]
    )
    assert sample.exit_code == 0, sample.output
    assert (tmp_path / "s.zip").stat().st_size > 0

    review = runner.invoke(
        app, ["review", "--dataset", str(version_dir), "--n", "4", "--out", str(tmp_path / "rev")]
    )
    assert review.exit_code == 0, review.output
    assert (tmp_path / "rev" / "revisao.csv").exists()


def test_cli_sem_chave_de_llm_explica_o_que_fazer(tmp_path: Path):
    result = CliRunner().invoke(app, ["expand", "--provider", "groq", "--max-families", "1"])
    assert result.exit_code == 1
    assert "GROQ_API_KEY" in result.output
