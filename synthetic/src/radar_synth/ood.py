"""Conjunto fora de distribuição: conversas escritas inteiras por um LLM, não pelos templates.

Serve para medir se os modelos generalizam para um jeito de escrever que eles nunca viram. O LLM
recebe um cenário (setor, perfis, eventos) e devolve a conversa já rotulada. Antes de entrar no
dataset, tudo é validado: rótulos fora da taxonomia ou do papel saem, e **todo dado pessoal que o
LLM escreveu é trocado por um dado falso nosso** (nada que ele inventar fica no dataset).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from radar.taxonomy import (
    CUSTOMER_LABELS,
    DEFAULT_SEVERITY,
    LABELS_PT,
    PII_TYPES,
    SELLER_LABELS,
)
from radar_synth.fake import FakeData
from radar_synth.llm import ChatClient, LLMError, parse_json
from radar_synth.model import ExpectedAlert, PiiAnnotation, SynthConversation, SynthMessage
from radar_synth.profiles import CUSTOMER_PROFILES, SELLER_PROFILES

SYSTEM_PROMPT = (
    "Você escreve conversas realistas de WhatsApp entre um vendedor e um cliente no Brasil, em "
    "português informal, para um dataset sintético de treino de modelos de compliance. Todos os "
    "nomes, documentos, telefones e e-mails devem ser inventados. Responda apenas com JSON."
)

_EVENTS = (
    "promessa_indevida",
    "informacao_enganosa",
    "pressao_abusiva",
    "pagamento_fora_canal",
    "linguagem_inadequada",
    "dados_pessoais_indevidos",
    "objecao_preco",
    "objecao_confianca",
    "objecao_prazo",
    "objecao_vou_pensar",
    "objecao_concorrente",
    "objecao_cancelamento",
    "pedido_pendente",
    "sinal_compra",
)


def _scenario(rng: random.Random, sector: str) -> dict[str, Any]:
    seller = rng.choice(sorted(SELLER_PROFILES))
    events = rng.sample(_EVENTS, rng.randint(1, 3))
    if seller == "bom":
        events = [e for e in events if e in CUSTOMER_LABELS or e == "pedido_pendente"] or [
            "objecao_preco"
        ]
    return {
        "setor": sector,
        "perfil_vendedor": seller,
        "perfil_cliente": rng.choice(sorted(CUSTOMER_PROFILES)),
        "eventos": events,
        "mensagens": rng.randint(8, 18),
    }


def _prompt(scenario: dict[str, Any]) -> str:
    seller_labels = ", ".join(f"{k} ({LABELS_PT[k]})" for k in sorted(SELLER_LABELS))
    customer_labels = ", ".join(f"{k} ({LABELS_PT[k]})" for k in sorted(CUSTOMER_LABELS))
    return (
        f"Cenário: setor {scenario['setor']}, vendedor de perfil {scenario['perfil_vendedor']}, "
        f"cliente de perfil {scenario['perfil_cliente']}, cerca de {scenario['mensagens']} "
        f"mensagens. A conversa precisa conter: {', '.join(scenario['eventos'])}.\n\n"
        f"Rótulos de mensagens do vendedor: {seller_labels}.\n"
        f"Rótulos de mensagens do cliente: {customer_labels}.\n"
        "Tipos de dado pessoal: " + ", ".join(PII_TYPES) + ".\n\n"
        "Formato da resposta:\n"
        '{"mensagens": [{"de": "cliente|vendedor", "texto": "...", "rotulos": ["..."], '
        '"dados_pessoais": [{"tipo": "CPF", "valor": "trecho exato do texto"}], "audio": false}], '
        '"alertas": [{"tipo": "promessa_indevida|pedido_pendente|objecao_sem_resposta|'
        'sinal_compra_ignorado|...", "mensagem": 0}]}\n'
        "Rotule só o que a mensagem realmente faz. Negar uma promessa ('não posso garantir') não "
        "é promessa. Use 'audio': true em algumas mensagens do cliente, escritas como fala."
    )


def _fake_value(fake: FakeData, kind: str, original: str) -> str:
    if kind == "NOME_PESSOA":
        return fake.full_name() if len(original.split()) > 1 else fake.first_name()
    if kind == "CPF":
        return fake.cpf(formatted="." in original or "-" in original)
    if kind == "CNPJ":
        return fake.cnpj(formatted="/" in original)
    if kind == "RG":
        return fake.rg()
    if kind == "TELEFONE":
        return fake.phone()
    if kind == "EMAIL":
        return fake.email(fake.full_name())
    if kind == "ENDERECO":
        return fake.address()
    if kind == "CEP":
        return fake.cep(formatted="-" in original)
    if kind == "PIX":
        return fake.pix_random_key()
    if kind == "CONTA_BANCARIA":
        return fake.bank_account()[1]
    return fake.plate()


def _replace_pii(
    text: str, items: list[Any], fake: FakeData, mapping: dict[str, str]
) -> tuple[str, list[PiiAnnotation]]:
    found: list[tuple[int, int, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind, value = str(item.get("tipo", "")), str(item.get("valor", ""))
        if kind not in PII_TYPES or not value:
            continue
        start = 0
        while (position := text.find(value, start)) >= 0:
            found.append((position, position + len(value), kind))
            start = position + len(value)
    found.sort()
    annotations: list[PiiAnnotation] = []
    out: list[str] = []
    cursor = 0
    for start, end, kind in found:
        if start < cursor:
            continue  # sobreposto a um trecho já trocado
        original = text[start:end]
        replacement = mapping.setdefault(f"{kind}|{original}", _fake_value(fake, kind, original))
        out.append(text[cursor:start])
        position = sum(len(chunk) for chunk in out)
        out.append(replacement)
        annotations.append(PiiAnnotation(kind, position, position + len(replacement), replacement))
        cursor = end
    out.append(text[cursor:])
    return "".join(out), annotations


def generate_ood_conversation(
    client: ChatClient, *, seed: int, sector: str, conversation_id: str | None = None
) -> SynthConversation:
    rng = random.Random(f"ood:{sector}:{seed}")
    fake = FakeData(rng)
    scenario = _scenario(rng, sector)
    data = parse_json(client.complete(SYSTEM_PROMPT, _prompt(scenario)))
    if not isinstance(data, dict) or not isinstance(data.get("mensagens"), list):
        raise LLMError("resposta sem a lista de mensagens")

    seller_name, customer_name = fake.full_name(), fake.full_name()
    clock = datetime(2025, 1, 6, 9, 0) + timedelta(
        days=rng.randrange(300), minutes=rng.randrange(600)
    )
    mapping: dict[str, str] = {}
    messages: list[SynthMessage] = []
    index_map: dict[int, int] = {}
    for original_index, raw in enumerate(data["mensagens"]):
        if not isinstance(raw, dict) or raw.get("de") not in ("cliente", "vendedor"):
            continue
        text = str(raw.get("texto", "")).strip()
        if not text:
            continue
        sender = str(raw["de"])
        allowed = SELLER_LABELS if sender == "vendedor" else CUSTOMER_LABELS
        labels = sorted({str(label) for label in raw.get("rotulos") or [] if label in allowed})
        text, pii = _replace_pii(text, raw.get("dados_pessoais") or [], fake, mapping)
        clock += timedelta(minutes=rng.uniform(0.5, 45))
        index_map[original_index] = len(messages)
        messages.append(
            SynthMessage(
                index=len(messages),
                sender=sender,
                author=seller_name if sender == "vendedor" else customer_name,
                timestamp=clock.replace(microsecond=0),
                kind="audio" if raw.get("audio") is True and sender == "cliente" else "texto",
                text=text,
                labels=labels,
                pii=pii,
                act="ood",
                family=f"ood.{client.name}",
                stage="negociacao",
            )
        )
    if len(messages) < 2:
        raise LLMError("conversa curta demais")

    alerts = []
    for raw in data.get("alertas") or []:
        if not isinstance(raw, dict):
            continue
        kind, index = raw.get("tipo"), raw.get("mensagem")
        if kind in DEFAULT_SEVERITY and isinstance(index, int) and index in index_map:
            alerts.append(
                ExpectedAlert(str(kind), DEFAULT_SEVERITY[str(kind)].value, index_map[index])
            )

    return SynthConversation(
        id=conversation_id or f"ood-{sector}-{seed:05d}",
        seed=seed,
        sector=sector,
        split="ood",
        seller_profile=scenario["perfil_vendedor"],
        customer_profile=scenario["perfil_cliente"],
        outcome="em_andamento",
        company="Empresa Exemplo",
        seller_display=seller_name,
        customer_display=customer_name,
        messages=messages,
        exported_at=clock + timedelta(hours=2),
        expected_alerts=alerts,
        generator_version=f"llm:{client.name}:{client.model}",
    )
