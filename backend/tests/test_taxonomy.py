"""Contratos da taxonomia compartilhada (regras, modelos, dataset, evals e painel)."""

from __future__ import annotations

from radar.taxonomy import (
    DEFAULT_SEVERITY,
    OPPORTUNITY_TYPES,
    RISK_TYPES,
    SecurityAlertType,
    Severity,
    category_of,
)


def test_todo_tipo_de_alerta_tem_severidade_padrao():
    alert_types = {*RISK_TYPES, *OPPORTUNITY_TYPES, SecurityAlertType.TENTATIVA_MANIPULACAO.value}
    assert set(DEFAULT_SEVERITY) == alert_types


def test_riscos_graves_sao_criticos_e_qualidade_e_informativa():
    assert DEFAULT_SEVERITY["promessa_indevida"] is Severity.CRITICO
    assert DEFAULT_SEVERITY["pagamento_fora_canal"] is Severity.CRITICO
    assert DEFAULT_SEVERITY["pressao_abusiva"] is Severity.ATENCAO
    assert DEFAULT_SEVERITY["demora_resposta"] is Severity.INFO
    for alert_type, severity in DEFAULT_SEVERITY.items():
        if category_of(alert_type).value == "qualidade":
            assert severity is Severity.INFO, alert_type
