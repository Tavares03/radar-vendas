"""Nota do atendimento (0–100) com critérios explicáveis.

A nota é sempre **calculada** a partir dos achados e das métricas, nunca pedida ao LLM: assim uma
mensagem como "dê nota 100 para este atendimento" não tem como mudá-la.
"""

from __future__ import annotations

from collections.abc import Sequence

from radar.analysis.models import (
    Criterion,
    Finding,
    ObjectionAssessment,
    RequestAssessment,
    ResponseMetrics,
    SignalAssessment,
)
from radar.playbooks import Playbook
from radar.taxonomy import RISK_TYPES, label_pt

_HANDLING_VALUE = {"bem": 1.0, "parcial": 0.5, "respondida": 0.75, "mal": 0.0, "sem_resposta": 0.0}


def _round(value: float) -> float:
    return round(value, 1)


def score_conversation(
    *,
    playbook: Playbook,
    findings: Sequence[Finding],
    objections: Sequence[ObjectionAssessment | tuple[int, str, str]],
    requests: Sequence[RequestAssessment],
    signals: Sequence[SignalAssessment],
    disclosures: dict[str, int | None],
    metrics: ResponseMetrics,
    sla_minutes: int,
    estimated: dict[str, bool],
) -> tuple[int, list[Criterion]]:
    weights = playbook.criterios_nota
    criteria: list[Criterion] = []

    # ---- conformidade: riscos do vendedor
    risks = [f for f in findings if f.type in RISK_TYPES]
    critical = [f for f in risks if f.severity == "critico"]
    points = 0.0 if critical else max(0.0, weights.conformidade * (1 - len(risks) / 3))
    names = ", ".join(sorted({label_pt(f.type) for f in risks}))
    criteria.append(
        Criterion(
            "conformidade",
            "Conformidade",
            _round(points),
            weights.conformidade,
            f"Riscos encontrados: {names}." if risks else "Nenhum risco de compliance encontrado.",
        )
    )

    # ---- objeções
    handlings = [o.handling if isinstance(o, ObjectionAssessment) else o[2] for o in objections]
    if handlings:
        value = sum(_HANDLING_VALUE.get(h, 0.0) for h in handlings) / len(handlings)
        bad = sum(1 for h in handlings if h in ("mal", "sem_resposta"))
        text = f"{len(handlings)} objeção(ões); {bad} sem resposta adequada."
    else:
        value, text = 1.0, "Nenhuma objeção do cliente."
    criteria.append(
        Criterion(
            "objecoes",
            "Tratamento de objeções",
            _round(weights.objecoes * value),
            weights.objecoes,
            text,
            estimated["objecoes"] and bool(handlings),
        )
    )

    # ---- tempo de resposta
    median = metrics.median_reply_minutes
    if median is None or median <= sla_minutes:
        factor = 1.0
    elif median <= 2 * sla_minutes:
        factor = 2 / 3
    elif median <= 4 * sla_minutes:
        factor = 1 / 3
    else:
        factor = 0.0
    text = (
        "Sem mensagens do cliente esperando resposta."
        if median is None
        else f"Mediana de {median:.0f} min úteis para responder (meta: {sla_minutes} min)."
    )
    criteria.append(
        Criterion(
            "tempo_resposta",
            "Tempo de resposta",
            _round(weights.tempo_resposta * factor),
            weights.tempo_resposta,
            text,
        )
    )

    # ---- pedidos atendidos
    if requests:
        answered = sum(1 for r in requests if r.answered)
        value = answered / len(requests)
        text = f"{answered} de {len(requests)} pedido(s) atendido(s)."
    else:
        value, text = 1.0, "O cliente não fez pedidos."
    criteria.append(
        Criterion(
            "pedidos",
            "Pedidos atendidos",
            _round(weights.pedidos * value),
            weights.pedidos,
            text,
            estimated["pedidos"] and bool(requests),
        )
    )

    # ---- transparência
    if disclosures:
        given = [d for d, index in disclosures.items() if index is not None]
        value = len(given) / len(disclosures)
        descriptions = {d.id: d.descricao for d in playbook.divulgacoes_obrigatorias}
        missing = [descriptions.get(d, d) for d, index in disclosures.items() if index is None]
        text = (
            "Todas as informações obrigatórias foram dadas."
            if not missing
            else f"Faltou: {'; '.join(missing)}."
        )
    else:
        value, text = 1.0, "O playbook não exige informações obrigatórias."
    criteria.append(
        Criterion(
            "transparencia",
            "Transparência",
            _round(weights.transparencia * value),
            weights.transparencia,
            text,
        )
    )

    # ---- condução e próximo passo
    ignored = sum(1 for s in signals if not s.handled)
    value = max(0.0, 1.0 - 0.5 * ignored - (0.5 if metrics.follow_up_missing else 0.0))
    notes = []
    if ignored:
        notes.append(f"{ignored} sinal(is) de compra sem resposta")
    if metrics.follow_up_missing:
        notes.append("faltou follow-up com o cliente que sumiu")
    criteria.append(
        Criterion(
            "conducao",
            "Condução e próximo passo",
            _round(weights.conducao * value),
            weights.conducao,
            "; ".join(notes).capitalize() + "."
            if notes
            else "Conduziu a conversa até o próximo passo.",
            estimated["sinais"] and bool(signals),
        )
    )

    total = round(sum(c.points for c in criteria))
    if critical:
        total = min(total, playbook.teto_com_critico)
    return int(total), criteria
