"""Dataset: splits sem vazamento de template, arquivos, manifesto e conjunto de desafio."""

from __future__ import annotations

import json
from pathlib import Path

from radar.privacy.validators import is_valid_cpf
from radar_synth.banks import SECTORS, load_bank
from radar_synth.challenge import load_challenge
from radar_synth.dataset import (
    SPLITS,
    build_dataset,
    dataset_version,
    family_splits,
    write_dataset,
)

SIZES = {"train": 40, "validation": 10, "test": 10}


def test_toda_familia_tem_split_e_cada_ato_aparece_em_todos_os_splits():
    assignment = family_splits()
    for sector in SECTORS:
        for act in load_bank(sector).acts.values():
            for split in SPLITS:
                assert any(split in assignment[f] for f in act.families), (sector, act.name, split)


def test_familias_de_treino_nunca_aparecem_em_validacao_ou_teste():
    assignment = family_splits()
    conversations = build_dataset(sizes=SIZES, seed=1)
    families = {split: set() for split in SPLITS}  # type: ignore[var-annotated]
    for conversation in conversations:
        families[conversation.split] |= set(conversation.families)
        for family in conversation.families:
            assert conversation.split in assignment[family]
    assert not families["train"] & families["validation"]
    assert not families["train"] & families["test"]


def test_dataset_e_deterministico():
    first = [c.to_dict() for c in build_dataset(sizes=SIZES, seed=7)]
    second = [c.to_dict() for c in build_dataset(sizes=SIZES, seed=7)]
    assert first == second
    assert first != [c.to_dict() for c in build_dataset(sizes=SIZES, seed=8)]


def test_setores_distribuidos_e_ids_unicos():
    conversations = build_dataset(sizes=SIZES, seed=2)
    assert {c.sector for c in conversations} == set(SECTORS)
    assert len({c.id for c in conversations}) == len(conversations)


def test_arquivos_gerados(tmp_path: Path):
    conversations = build_dataset(sizes=SIZES, seed=3)
    manifest = write_dataset(conversations, tmp_path, exports_per_split=2)

    for split in SPLITS:
        rows = (
            (tmp_path / "conversations" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
        )
        assert len(rows) == SIZES[split]
        messages = [
            json.loads(line)
            for line in (tmp_path / "messages" / f"{split}.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert messages
        assert {"text", "labels", "sender", "conversation_id"} <= set(messages[0])
        ner = [
            json.loads(line)
            for line in (tmp_path / "ner" / f"{split}.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        for row in ner:
            for entity in row["entities"]:
                assert row["text"][entity["start"] : entity["end"]] == entity["value"]
        assert len(list((tmp_path / "exports" / split).glob("*.zip"))) == 2

    saved = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert saved["version"] == manifest["version"] == dataset_version()
    assert saved["conversations"] == SIZES
    assert saved["labels"]["train"]["objecao_preco"] > 0
    assert set(saved["files"]) >= {"conversations/train.jsonl", "ner/test.jsonl"}


def test_todo_tipo_de_dado_pessoal_aparece_em_todos_os_splits():
    from radar.taxonomy import PII_TYPES

    conversations = build_dataset(sizes={"train": 150, "validation": 100, "test": 100}, seed=11)
    for split in SPLITS:
        found = {
            p.type for c in conversations if c.split == split for m in c.messages for p in m.pii
        }
        assert found == set(PII_TYPES), (split, set(PII_TYPES) - found)


def test_cpfs_do_dataset_sao_validos():
    for conversation in build_dataset(sizes=SIZES, seed=4):
        for message in conversation.messages:
            for span in message.pii:
                if span.type == "CPF":
                    assert is_valid_cpf(span.value)


def test_conjunto_de_desafio_tem_anotacoes_coerentes():
    challenge = load_challenge()
    assert len(challenge) >= 15
    categories = {c.sector for c in challenge}
    assert categories <= set(SECTORS)
    for conversation in challenge:
        assert conversation.split == "desafio"
        for message in conversation.messages:
            for span in message.pii:
                assert message.text[span.start : span.end] == span.value
    # Casos negativos difíceis: negação que não pode virar alerta.
    negations = [c for c in challenge if c.id.startswith("desafio-negacao")]
    assert negations
    assert all(not c.expected_alerts for c in negations)
