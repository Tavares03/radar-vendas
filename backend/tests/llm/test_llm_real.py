"""Ponta a ponta com um LLM de verdade (Groq, Gemini, OpenRouter ou Ollama).

Roda só com ``RADAR_RUN_NETWORK_TESTS=1`` e uma chave gratuita no ambiente, por exemplo:

    RADAR_RUN_NETWORK_TESTS=1 GROQ_API_KEY=... RADAR_LLM_MODE=cloud uv run pytest backend/tests/llm/test_llm_real.py
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from radar.analysis import ConversationInput, MessageInput, analyze_conversation
from radar.analysis.llm_analyzer import RouterAnalyzer
from radar.config import Settings
from radar.llm import build_router
from radar.playbooks import load_playbook
from radar.taxonomy import SenderRole
from radar.tenant_settings import BusinessHours

pytestmark = pytest.mark.network

V, C = SenderRole.VENDEDOR, SenderRole.CLIENTE
T0 = datetime(2025, 3, 11, 13, 0, tzinfo=UTC)
LINES = [
    (C, "Oi, quero entender o consórcio de carro. Em quanto tempo sou contemplado?"),
    (V, "Fica tranquilo, comigo você sai contemplado já no segundo mês, pode confiar!"),
    (C, "Achei a parcela meio cara..."),
    (V, "Se não fechar hoje perde a condição, decide agora"),
    (C, "Me manda uma simulação por escrito?"),
    (V, "Depois te mando"),
]


def test_llm_real_confirma_promessa_e_resume():
    settings = Settings(llm_mode="cloud")
    router = build_router(settings, "cloud") or build_router(settings, "local")
    if router is None:
        pytest.skip("nenhuma chave de LLM nem Ollama configurado")
    messages = [
        MessageInput(i, s, t, T0 + timedelta(minutes=3 * i)) for i, (s, t) in enumerate(LINES)
    ]
    conversation = ConversationInput(
        messages=messages,
        playbook=load_playbook("consorcio"),
        timezone=ZoneInfo("America/Sao_Paulo"),
        business_hours=BusinessHours(),
        reference_time=messages[-1].sent_at + timedelta(hours=1),
    )

    analysis = analyze_conversation(conversation, llm=RouterAnalyzer(router))

    assert analysis.llm_error is None, analysis.llm_error
    assert analysis.layers[-1] == "llm"
    types = {f.type for f in analysis.findings}
    assert "promessa_indevida" in types
    assert "pressao_abusiva" in types
    assert analysis.summary
    assert analysis.suggestion
    promise = next(f for f in analysis.findings if f.type == "promessa_indevida")
    assert promise.sources.get("llm", {}).get("confirmado") is not False
