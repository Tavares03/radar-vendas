"""Indicadores do painel: visão geral da empresa e desempenho por vendedor.

O período é contado a partir da atividade mais recente da empresa (não do relógio): uma base
importada de exports antigos continua mostrando a tendência dela.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.db.models import Alert, Analysis, Conversation, Seller
from radar.services.analysis import OPEN_STATUSES
from radar.taxonomy import OBJECTION_TYPES, label_pt

WEEKS = 8


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _reference(db: Session) -> datetime:
    latest = _aware(db.scalar(select(func.max(Conversation.last_message_at))))
    return latest or datetime.now(UTC)


def _week_start(moment: datetime) -> date:
    day = moment.date()
    return day - timedelta(days=day.weekday())


def _weekly(
    conversations: list[Conversation], reference: datetime, critical: Counter[uuid.UUID]
) -> list[dict[str, Any]]:
    first = _week_start(reference) - timedelta(weeks=WEEKS - 1)
    buckets: dict[date, list[Conversation]] = {first + timedelta(weeks=i): [] for i in range(WEEKS)}
    for conversation in conversations:
        moment = _aware(conversation.last_message_at)
        if moment is None:
            continue
        week = _week_start(moment)
        if week in buckets:
            buckets[week].append(conversation)
    weekly = []
    for week, items in sorted(buckets.items()):
        scores = [c.score for c in items if c.score is not None]
        weekly.append(
            {
                "week_start": week.isoformat(),
                "conversations": len(items),
                "average_score": round(sum(scores) / len(scores), 1) if scores else None,
                "critical_alerts": sum(critical[c.id] for c in items),
            }
        )
    return weekly


def _critical_by_conversation(db: Session, ids: list[uuid.UUID]) -> Counter[uuid.UUID]:
    if not ids:
        return Counter()
    rows = db.execute(
        select(Alert.conversation_id, func.count())
        .where(
            Alert.conversation_id.in_(ids),
            Alert.severity == "critico",
            Alert.status.in_(OPEN_STATUSES),
        )
        .group_by(Alert.conversation_id)
    )
    return Counter(dict(rows.all()))


def overview(db: Session, *, days: int) -> dict[str, Any]:
    reference = _reference(db)
    since = reference - timedelta(days=days)
    conversations = list(
        db.scalars(
            select(Conversation).where(
                Conversation.analyzed_at.is_not(None), Conversation.last_message_at >= since
            )
        )
    )
    ids = [c.id for c in conversations]
    critical = _critical_by_conversation(db, ids)
    scores = [c.score for c in conversations if c.score is not None]

    # A tendência cobre sempre as mesmas semanas, qualquer que seja o período escolhido: com
    # "30 dias" o gráfico ficava com as primeiras semanas vazias, como se não tivesse havido conversa.
    trend_start = datetime.combine(
        _week_start(reference) - timedelta(weeks=WEEKS - 1), datetime.min.time(), tzinfo=UTC
    )
    if trend_start < since:
        trend = list(
            db.scalars(
                select(Conversation).where(
                    Conversation.analyzed_at.is_not(None),
                    Conversation.last_message_at >= trend_start,
                )
            )
        )
        trend_critical = _critical_by_conversation(db, [c.id for c in trend])
    else:
        trend, trend_critical = conversations, critical

    # "Em aberto" é sobre agora: conta os alertas de todas as conversas, não só as do período.
    open_alerts = {"critico": 0, "atencao": 0, "info": 0}
    types: Counter[str] = Counter()
    for severity, alert_type, count in db.execute(
        select(Alert.severity, Alert.type, func.count())
        .where(Alert.status.in_(OPEN_STATUSES))
        .group_by(Alert.severity, Alert.type)
    ):
        open_alerts[severity] = open_alerts.get(severity, 0) + count
        types[alert_type] += count

    by_seller: dict[uuid.UUID, list[Conversation]] = defaultdict(list)
    for conversation in conversations:
        if conversation.seller_id is not None:
            by_seller[conversation.seller_id].append(conversation)
    sellers = []
    for seller_id, items in by_seller.items():
        seller = db.get(Seller, seller_id)
        seller_scores = [c.score for c in items if c.score is not None]
        sellers.append(
            {
                "seller_id": seller_id,
                "name": seller.display_name if seller else "Vendedor removido",
                "conversations": len(items),
                "average_score": round(sum(seller_scores) / len(seller_scores), 1)
                if seller_scores
                else None,
                "open_alerts": sum(c.open_alerts for c in items),
                "critical_alerts": sum(critical[c.id] for c in items),
            }
        )
    sellers.sort(key=lambda s: (s["average_score"] is None, s["average_score"] or 0))

    return {
        "period_days": days,
        "reference_date": reference.date().isoformat(),
        "conversations_analyzed": len(conversations),
        "average_score": round(sum(scores) / len(scores), 1) if scores else None,
        "open_alerts": open_alerts,
        "weekly": _weekly(trend, reference, trend_critical),
        "sellers": sellers,
        "alert_types": [
            {"type": t, "label": label_pt(t), "count": n} for t, n in types.most_common(8)
        ],
    }


def seller_performance(db: Session, seller: Seller) -> dict[str, Any]:
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.seller_id == seller.id, Conversation.analyzed_at.is_not(None))
            .order_by(Conversation.last_message_at.desc().nulls_last())
        )
    )
    ids = [c.id for c in conversations]
    scores = [c.score for c in conversations if c.score is not None]
    critical = _critical_by_conversation(db, ids)

    alert_types: Counter[str] = Counter()
    if ids:
        for alert_type, count in db.execute(
            select(Alert.type, func.count())
            .where(Alert.conversation_id.in_(ids), Alert.status.in_(OPEN_STATUSES))
            .group_by(Alert.type)
        ):
            alert_types[alert_type] = count

    analyses = (
        list(
            db.scalars(
                select(Analysis).where(
                    Analysis.conversation_id.in_(ids), Analysis.is_current.is_(True)
                )
            )
        )
        if ids
        else []
    )
    objections: dict[str, Counter[str]] = {t: Counter() for t in OBJECTION_TYPES}
    criteria: dict[str, list[float]] = defaultdict(list)
    criteria_meta: dict[str, tuple[str, int]] = {}
    improvements: Counter[str] = Counter()
    for analysis in analyses:
        for item in (analysis.details or {}).get("objections", []):
            if item.get("type") in objections:
                objections[item["type"]][item.get("handling", "parcial")] += 1
        for criterion in analysis.criteria or []:
            criteria[criterion["id"]].append(float(criterion["points"]))
            criteria_meta[criterion["id"]] = (criterion["label"], int(criterion["maximum"]))
        improvements.update((analysis.details or {}).get("improvements", []))

    reference = _aware(conversations[0].last_message_at) if conversations else None
    return {
        "seller": {"id": seller.id, "display_name": seller.display_name},
        "conversations": len(conversations),
        "average_score": round(sum(scores) / len(scores), 1) if scores else None,
        "weekly": _weekly(conversations, reference or datetime.now(UTC), critical),
        "alerts_by_type": [
            {"type": t, "label": label_pt(t), "count": n} for t, n in alert_types.most_common()
        ],
        "objections": [
            {
                "type": t,
                "label": label_pt(t),
                "total": sum(c.values()),
                **{h: c.get(h, 0) for h in ("bem", "parcial", "mal", "sem_resposta")},
            }
            for t, c in objections.items()
            if sum(c.values())
        ],
        "criteria": [
            {
                "id": key,
                "label": criteria_meta[key][0],
                "average_points": round(sum(v) / len(v), 1),
                "maximum": criteria_meta[key][1],
            }
            for key, v in criteria.items()
        ],
        "improvements": [text for text, _ in improvements.most_common(5)],
        "recent": conversations[:10],
    }
