"""Revisão humana por amostragem: separa conversas variadas e gera um roteiro de conferência.

Gera um Markdown legível (conversa com rótulos e dados pessoais destacados) e uma planilha CSV com
uma linha por mensagem e colunas ``ok``/``correcao``/``comentario`` para quem revisa preencher.
"""

from __future__ import annotations

import csv
import random
from collections.abc import Sequence
from pathlib import Path

from radar.taxonomy import label_pt
from radar_synth.model import SynthConversation


def select_review_sample(
    conversations: Sequence[SynthConversation], *, n: int, seed: int = 0
) -> list[SynthConversation]:
    """Amostra estratificada: cobre setores, perfis de vendedor e o máximo de rótulos possível."""
    rng = random.Random(seed)
    pool = sorted(conversations, key=lambda c: c.id)
    rng.shuffle(pool)
    chosen: list[SynthConversation] = []

    def take(predicate_key: str, values: set[str]) -> None:
        for value in sorted(values):
            if len(chosen) >= n:
                return
            for conversation in pool:
                if conversation in chosen:
                    continue
                keys = {
                    "sector": {conversation.sector},
                    "seller": {conversation.seller_profile},
                    "label": {label for m in conversation.messages for label in m.labels},
                    "alert": {a.type for a in conversation.expected_alerts},
                }[predicate_key]
                if value in keys:
                    chosen.append(conversation)
                    break

    take("sector", {c.sector for c in pool})
    take("seller", {c.seller_profile for c in pool})
    take("label", {label for c in pool for m in c.messages for label in m.labels})
    take("alert", {a.type for c in pool for a in c.expected_alerts})
    for conversation in pool:
        if len(chosen) >= n:
            break
        if conversation not in chosen:
            chosen.append(conversation)
    return chosen[:n]


def _highlight(text: str, spans: Sequence[tuple[int, int, str]]) -> str:
    out, cursor = [], 0
    for start, end, kind in sorted(spans):
        out.append(text[cursor:start])
        out.append(f"«{text[start:end]}»`{kind}`")
        cursor = end
    out.append(text[cursor:])
    return "".join(out).replace("\n", " ⏎ ")


def write_review(sample: Sequence[SynthConversation], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Revisão por amostragem do dataset sintético",
        "",
        "Confira em cada mensagem: o rótulo faz sentido? Os dados pessoais estão marcados certo "
        "(trecho e tipo)? Os alertas esperados são os que um gestor esperaria? Anote na planilha "
        "`revisao.csv` (coluna `ok` com `s`/`n`, e a correção quando houver).",
        "",
    ]
    for conversation in sample:
        lines += [
            f"## {conversation.id} · {conversation.sector}",
            "",
            f"Vendedor **{conversation.seller_profile}** · cliente **{conversation.customer_profile}**"
            f" · desfecho **{conversation.outcome}** · split `{conversation.split}`",
            "",
        ]
        for message in conversation.messages:
            spans = [(p.start, p.end, p.type) for p in message.pii]
            labels = ", ".join(label_pt(label) for label in message.labels)
            audio = " 🎤" if message.kind == "audio" else ""
            suffix = f" — **{labels}**" if labels else ""
            lines.append(
                f"- `{message.index:02d}` {message.timestamp:%d/%m %H:%M} *{message.sender}*{audio}: "
                f"{_highlight(message.text, spans)}{suffix}"
            )
        alerts = ", ".join(
            f"{label_pt(a.type)} ({a.severity}, msg {a.message_index})"
            for a in conversation.expected_alerts
        )
        lines += ["", f"**Alertas esperados:** {alerts or 'nenhum'}", ""]
    markdown = out_dir / "revisao.md"
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sheet = out_dir / "revisao.csv"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "conversa",
                "mensagem",
                "quem",
                "texto",
                "rotulos",
                "dados_pessoais",
                "ok",
                "correcao",
                "comentario",
            ]
        )
        for conversation in sample:
            for message in conversation.messages:
                writer.writerow(
                    [
                        conversation.id,
                        message.index,
                        message.sender,
                        message.text,
                        "|".join(message.labels),
                        "|".join(f"{p.type}:{p.value}" for p in message.pii),
                        "",
                        "",
                        "",
                    ]
                )
    return markdown, sheet
