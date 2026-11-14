"""Métricas determinísticas: tempo de resposta em horário comercial, silêncio e follow-up."""

from __future__ import annotations

import re
import statistics
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from radar.analysis.models import ConversationInput, ResponseMetrics
from radar.taxonomy import SenderRole
from radar.tenant_settings import BusinessHours
from radar.textutil import fold

#: O cliente encerrou a conversa (agradeceu, se despediu ou desistiu): não falta follow-up.
_CLOSING_RE = re.compile(
    r"\b(?:obrigad|brigad|obg|valeu|vlw|tchau|ate mais|ate logo|nao tenho mais interesse|desisti"
    r"|nao vai (?:dar|rolar)|pode me tirar da lista|mudei de planos)"
)
#: Um follow-up é uma mensagem do vendedor enviada pelo menos este tempo depois do cliente.
FOLLOW_UP_GAP = timedelta(hours=20)


def business_minutes(start: datetime, end: datetime, hours: BusinessHours, zone: ZoneInfo) -> int:
    """Minutos entre ``start`` e ``end`` (com fuso) dentro do horário de atendimento da empresa."""
    if end <= start:
        return 0
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    total = 0.0
    day: date = local_start.date()
    while day <= local_end.date():
        if day.weekday() in hours.weekdays:
            opens = datetime.combine(day, hours.start, tzinfo=zone)
            closes = datetime.combine(
                day, hours.end if hours.end > hours.start else time(23, 59), tzinfo=zone
            )
            overlap = (min(local_end, closes) - max(local_start, opens)).total_seconds()
            total += max(0.0, overlap)
        day += timedelta(days=1)
    return int(total // 60)


def is_closing(text: str) -> bool:
    return bool(_CLOSING_RE.search(fold(text)))


def compute_metrics(conversation: ConversationInput) -> ResponseMetrics:
    messages = conversation.messages
    metrics = ResponseMetrics()
    last_customer: int | None = None
    waiting: int | None = None  # última mensagem do cliente ainda sem resposta
    for message in messages:
        if message.sender is SenderRole.CLIENTE:
            last_customer = message.index
            waiting = message.index
        elif message.sender is SenderRole.VENDEDOR and waiting is not None:
            minutes = business_minutes(
                messages[waiting].sent_at,
                message.sent_at,
                conversation.business_hours,
                conversation.timezone,
            )
            metrics.replies.append((waiting, message.index, minutes))
            waiting = None
    if metrics.replies:
        values = [m for _, _, m in metrics.replies]
        metrics.median_reply_minutes = statistics.median(values)
        metrics.max_reply_minutes = max(values)

    if last_customer is None:
        return metrics
    customer_message = messages[last_customer]
    metrics.customer_closed = is_closing(customer_message.text)
    silence = conversation.reference_time - customer_message.sent_at
    metrics.silence_hours = silence.total_seconds() / 3600
    trailing = [m for m in messages[last_customer + 1 :] if m.sender is SenderRole.VENDEDOR]
    followed_up = any(m.sent_at - customer_message.sent_at >= FOLLOW_UP_GAP for m in trailing)
    metrics.follow_up_missing = (
        bool(trailing)
        and not followed_up
        and not metrics.customer_closed
        and metrics.silence_hours >= conversation.follow_up_hours
    )
    return metrics
