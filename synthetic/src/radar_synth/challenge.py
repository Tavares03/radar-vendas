"""Conjunto de desafio: conversas curtas escritas à mão com os casos em que regras simples erram."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import cache
from importlib import resources
from typing import Any

import yaml

from radar.taxonomy import DEFAULT_SEVERITY
from radar_synth import __version__
from radar_synth.model import ExpectedAlert, PiiAnnotation, SynthConversation, SynthMessage

_SELLER = "Carla Mendes"
_CUSTOMER = "Roberto Lima"
_START = datetime(2025, 3, 10, 9, 0, 0)


def _message(index: int, raw: list[Any]) -> SynthMessage:
    sender, text, labels, *rest = raw
    pii_spec = rest[0] if rest else []
    audio = bool(rest[1]) if len(rest) > 1 else False
    pii = []
    cursor = 0
    for kind, value in pii_spec:
        start = text.find(value, cursor)
        if start < 0:
            raise ValueError(f"desafio: '{value}' não está no texto da mensagem {index}")
        pii.append(PiiAnnotation(kind, start, start + len(value), value))
        cursor = start + len(value)
    return SynthMessage(
        index=index,
        sender=sender,
        author=_SELLER if sender == "vendedor" else _CUSTOMER,
        timestamp=_START + timedelta(minutes=3 * index),
        kind="audio" if audio else "texto",
        text=text,
        labels=list(labels),
        pii=pii,
        act="desafio",
        family="desafio",
        stage="negociacao",
    )


@cache
def load_challenge() -> tuple[SynthConversation, ...]:
    text = resources.files(__package__).joinpath("challenge.yaml").read_text(encoding="utf-8")
    conversations = []
    for item in yaml.safe_load(text):
        messages = [_message(i, raw) for i, raw in enumerate(item["mensagens"])]
        conversations.append(
            SynthConversation(
                id=item["id"],
                seed=0,
                sector=item["setor"],
                split="desafio",
                seller_profile="desafio",
                customer_profile="desafio",
                outcome="em_andamento",
                company="Empresa Exemplo",
                seller_display=_SELLER,
                customer_display=_CUSTOMER,
                messages=messages,
                exported_at=messages[-1].timestamp + timedelta(hours=1),
                expected_alerts=[
                    ExpectedAlert(kind, DEFAULT_SEVERITY[kind].value, index, item["descricao"])
                    for kind, index in item.get("alertas") or []
                ],
                generator_version=__version__,
            )
        )
    return tuple(conversations)
