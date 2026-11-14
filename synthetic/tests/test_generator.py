"""Gerador de conversas: determinismo, anotações coerentes e verdade de referência."""

from __future__ import annotations

from collections import Counter

import pytest

from radar.taxonomy import CUSTOMER_LABELS, RISK_TYPES, SELLER_LABELS
from radar_synth.banks import SECTORS
from radar_synth.generator import generate_conversation
from radar_synth.model import SynthConversation
from radar_synth.profiles import CUSTOMER_PROFILES, SELLER_PROFILES


def _many(n: int, **kwargs: object) -> list[SynthConversation]:
    return [generate_conversation(seed=seed, **kwargs) for seed in range(n)]  # type: ignore[arg-type]


def test_mesma_semente_gera_a_mesma_conversa():
    a = generate_conversation(seed=42, sector="consorcio")
    b = generate_conversation(seed=42, sector="consorcio")
    assert a.to_dict() == b.to_dict()
    assert generate_conversation(seed=43, sector="consorcio").to_dict() != a.to_dict()


@pytest.mark.parametrize("sector", SECTORS)
def test_anotacoes_batem_com_o_texto(sector: str):
    for conversation in _many(25, sector=sector):
        assert len(conversation.messages) >= 4
        for message in conversation.messages:
            assert message.text == message.text.strip()
            assert message.text
            for span in message.pii:
                assert 0 <= span.start < span.end <= len(message.text)
                assert message.text[span.start : span.end] == span.value
            allowed = SELLER_LABELS if message.sender == "vendedor" else CUSTOMER_LABELS
            assert set(message.labels) <= allowed


def test_horarios_nunca_voltam_no_tempo():
    for conversation in _many(30, sector="seguros"):
        times = [m.timestamp for m in conversation.messages]
        assert times == sorted(times)
        assert conversation.exported_at >= times[-1]


def test_vendedor_bom_nao_comete_riscos():
    for conversation in _many(40, sector="consorcio", seller_profile="bom"):
        risky = [m for m in conversation.messages if set(m.labels) & set(RISK_TYPES)]
        assert risky == [], [m.text for m in risky]


def test_vendedor_problematico_quase_sempre_comete_algum_risco():
    conversations = _many(40, sector="consorcio", seller_profile="problematico")
    with_risk = [c for c in conversations if any(a.type in RISK_TYPES for a in c.expected_alerts)]
    assert len(with_risk) >= 28


def test_todo_risco_rotulado_vira_alerta_esperado_e_vice_versa():
    for conversation in _many(60, sector="imobiliaria"):
        from_labels = {
            (label, m.index)
            for m in conversation.messages
            for label in m.labels
            if label in RISK_TYPES
        }
        from_alerts = {
            (a.type, a.message_index) for a in conversation.expected_alerts if a.type in RISK_TYPES
        }
        assert from_labels == from_alerts


def test_pedido_sem_resposta_vira_alerta_de_pedido_pendente():
    for conversation in _many(80, sector="generico"):
        pending = [r for r in conversation.requests if r.answered_by is None]
        alerts = [a for a in conversation.expected_alerts if a.type == "pedido_pendente"]
        assert len(alerts) == len({r.chain for r in pending})
        for request in conversation.requests:
            if request.answered_by is not None:
                assert request.answered_by > request.message_index
                assert conversation.messages[request.answered_by].sender == "vendedor"


def test_objecao_sem_resposta_vira_alerta():
    for conversation in _many(80, sector="clinica", seller_profile="medio"):
        unanswered = [o for o in conversation.objections if o.handling == "sem_resposta"]
        alerts = [a for a in conversation.expected_alerts if a.type == "objecao_sem_resposta"]
        assert len(unanswered) == len(alerts)


def test_alertas_tem_severidade_padrao():
    conversation = generate_conversation(seed=3, sector="consorcio", seller_profile="problematico")
    for alert in conversation.expected_alerts:
        assert alert.severity in {"info", "atencao", "critico"}


def test_variedade_de_perfis_setores_audios_e_mensagens_picotadas():
    conversations = [generate_conversation(seed=s, sector=SECTORS[s % 5]) for s in range(150)]
    assert {c.seller_profile for c in conversations} == set(SELLER_PROFILES)
    assert {c.customer_profile for c in conversations} == set(CUSTOMER_PROFILES)
    assert {c.outcome for c in conversations} == {"ganha", "perdida", "em_andamento", "esfriou"}
    kinds = Counter(m.kind for c in conversations for m in c.messages)
    assert kinds["audio"] > 20
    # mensagens picotadas: o mesmo autor manda várias seguidas
    assert any(
        a.sender == b.sender and a.act == b.act and a.family == b.family
        for c in conversations
        for a, b in zip(c.messages, c.messages[1:], strict=False)
    )
    labels = Counter(label for c in conversations for m in c.messages for label in m.labels)
    for label in ("objecao_preco", "pedido_cliente", "sinal_compra", "promessa_indevida"):
        assert labels[label] > 10, label


def test_tentativa_de_manipulacao_e_anotada():
    conversations = [generate_conversation(seed=s, sector="generico") for s in range(300)]
    injected = [c for c in conversations if any(m.act == "cliente.injecao" for m in c.messages)]
    assert injected
    for conversation in injected:
        assert any(a.type == "tentativa_manipulacao" for a in conversation.expected_alerts)


def test_filtro_de_familias_restringe_os_templates():
    allowed = {"comum.cliente.abertura.direto", "comum.vendedor.saudacao.bom_dia"}

    def only_some(family: str) -> bool:
        act = family.rsplit(".", 1)[0].split(".", 1)[1]
        if act in {"cliente.abertura", "vendedor.saudacao"}:
            return family in allowed
        return True

    conversation = generate_conversation(seed=9, sector="consorcio", allow_family=only_some)
    used = {
        m.family
        for m in conversation.messages
        if m.act in {"cliente.abertura", "vendedor.saudacao"}
    }
    assert used <= allowed


def _key(family: str) -> str:
    return family.rsplit(".", 1)[1]


def test_respostas_combinam_com_a_pergunta():
    pairs = {
        "vendedor.qualificacao": "cliente.responde_qualificacao",
        "cliente.pergunta_info": "vendedor.responde_info",
        "cliente.pergunta_garantia": "vendedor.negativa_correta",
    }
    checked = 0
    for seed in range(120):
        conversation = generate_conversation(seed=seed, sector="consorcio", seller_profile="bom")
        for a, b in zip(conversation.messages, conversation.messages[1:], strict=False):
            if pairs.get(a.act) == b.act:
                assert _key(a.family) == _key(b.family), (a.text, b.text)
                checked += 1
    assert checked > 50


def test_mesma_familia_nao_se_repete_seguida():
    for seed in range(80):
        conversation = generate_conversation(seed=seed, sector="generico")
        turns = [(m.act, m.family) for m in conversation.messages]
        distinct_turns = [t for i, t in enumerate(turns) if i == 0 or t != turns[i - 1]]
        families_by_act: dict[str, list[str]] = {}
        for act, family in distinct_turns:
            families_by_act.setdefault(act, []).append(family)
        for act, families in families_by_act.items():
            if len(families) <= 3:  # todo ato tem ao menos 3 famílias
                assert len(set(families)) == len(families), (act, families)


def test_demora_conta_so_minutos_do_horario_comercial():
    from datetime import datetime

    from radar_synth.generator import business_minutes

    friday_evening = datetime(2025, 3, 7, 17, 55)  # sexta-feira
    monday_morning = datetime(2025, 3, 10, 8, 10)
    assert business_minutes(friday_evening, monday_morning) == 15
    assert business_minutes(datetime(2025, 3, 10, 9, 0), datetime(2025, 3, 10, 11, 30)) == 150
    assert business_minutes(datetime(2025, 3, 8, 10, 0), datetime(2025, 3, 8, 15, 0)) == 0  # sábado


def test_ida_e_volta_pelo_dicionario():
    conversation = generate_conversation(seed=12, sector="seguros")
    assert SynthConversation.from_dict(conversation.to_dict()).to_dict() == conversation.to_dict()
