"""Conjunto da demonstração: a equipe fictícia, as datas e a troca de vendedor."""

from __future__ import annotations

import json
import re
import zipfile
from datetime import timedelta
from pathlib import Path

from radar.ingest import parse_chat
from radar_synth.demo import ANCHOR, COMPANY, TEAM, WEEKS, build_demo, recast, write_demo
from radar_synth.generator import generate_conversation
from radar_synth.writers import render_export

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples" / "demo"


def test_todas_as_conversas_sao_da_equipe_e_cabem_nas_semanas():
    conversations = build_demo()
    names = {member.name for member in TEAM}

    assert len(conversations) >= 40
    assert {c.seller_display for c in conversations} == names
    assert len({c.id for c in conversations}) == len(conversations)
    for conversation in conversations:
        last = conversation.messages[-1].timestamp.date()
        assert last < ANCHOR
        assert last >= ANCHOR - timedelta(weeks=WEEKS, days=7)
        authors = {m.author for m in conversation.messages if m.sender == "vendedor"}
        assert authors == {conversation.seller_display}
    # Toda semana tem conversa: o gráfico semanal da demonstração não fica com buraco.
    weeks = {(ANCHOR - c.messages[-1].timestamp.date()).days // 7 for c in conversations}
    assert set(range(WEEKS)) <= weeks


def test_a_mesma_semente_gera_a_mesma_demonstracao():
    def texts(seed: int) -> list[str]:
        return [
            render_export(c, platform="android", language="pt").chat_text for c in build_demo(seed)
        ]

    assert texts(3) == texts(3)
    assert texts(3) != texts(4)


def test_troca_de_vendedor_acerta_nome_artigo_empresa_e_datas():
    vera = next(member for member in TEAM if member.gender == "F")
    seed = next(
        s
        for s in range(1, 400)
        if any(
            re.search(r"\b[Aa]qui é o \w+", m.text) or re.search(r"\b[Ss]ou o \w+", m.text)
            for m in generate_conversation(seed=s, sector="consorcio").messages
        )
    )
    base = generate_conversation(seed=seed, sector="consorcio")
    original_first = base.seller_display.split()[0]

    moved = recast(base, vera, days=14)

    text = "\n".join(m.text for m in moved.messages)
    assert re.search(rf"\b(é|[Ss]ou) a {vera.first_name}\b", text)
    assert not re.search(rf"\bo {vera.first_name}\b", text)
    assert not re.search(rf"\b{original_first}\b", text)
    assert base.company not in text or base.company == COMPANY
    assert moved.seller_display == vera.name
    for before, after in zip(base.messages, moved.messages, strict=True):
        assert after.timestamp - before.timestamp == timedelta(days=14)
        assert after.timestamp.weekday() == before.timestamp.weekday()
    assert moved.exported_at - base.exported_at == timedelta(days=14)


def test_o_parser_do_radar_le_os_exports_da_demonstracao():
    for conversation in build_demo()[:8]:
        chat = parse_chat(render_export(conversation, platform="android", language="pt").chat_text)
        assert len([m for m in chat.messages if m.author]) == len(conversation.messages)
        assert conversation.seller_display in {m.author for m in chat.messages}


def test_arquivos_versionados_sao_os_que_o_gerador_produz(tmp_path: Path):
    count = write_demo(tmp_path)
    manifest = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert manifest["conversas"] == count
    assert manifest["equipe"] == [member.name for member in TEAM]
    assert manifest["ancora"] == ANCHOR.isoformat()

    # Compara o conteúdo, não os bytes do zip: a compressão muda entre versões da zlib.
    generated = {p.name: _contents(p) for p in sorted(tmp_path.iterdir())}
    committed = {p.name: _contents(p) for p in sorted(SAMPLES.iterdir())}
    assert generated.keys() == committed.keys()
    assert generated == committed, "data/samples/demo desatualizado: rode `uv run radar-synth demo`"


def _contents(path: Path) -> dict[str, bytes]:
    if path.suffix != ".zip":
        return {path.name: path.read_bytes()}
    with zipfile.ZipFile(path) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}
