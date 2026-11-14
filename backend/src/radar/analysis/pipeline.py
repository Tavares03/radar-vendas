"""Análise de uma conversa em camadas auditáveis: regras → classificador → métricas → LLM.

Regras de fusão:

- achado de **regra** nunca some em silêncio: se o LLM discorda, ele fica marcado como
  contestado, com o motivo registrado;
- achado só do **classificador** e refutado pelo LLM é descartado (e fica no rastro);
- achado só do **LLM** só vale se a evidência citada existir na conversa (grounding).

Cada camada pode faltar: sem LLM, objeções, pedidos e sinais de compra são avaliados por
heurística e os critérios da nota ficam marcados como estimados.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from radar.analysis.metrics import compute_metrics
from radar.analysis.models import (
    Candidate,
    ConversationAnalysis,
    ConversationInput,
    Finding,
    LLMAnalyzer,
    LLMReport,
    LLMUnavailable,
    MessageClassifier,
    ObjectionAssessment,
    RequestAssessment,
    SignalAssessment,
)
from radar.analysis.safety import ground, looks_like_injection
from radar.analysis.scoring import score_conversation
from radar.logs import get_logger
from radar.playbooks import RuleEngine
from radar.taxonomy import (
    OBJECTION_TYPES,
    RISK_TYPES,
    SELLER_LABELS,
    SenderRole,
    category_of,
)
from radar.textutil import fold

log = get_logger(__name__)

#: Mensagem do vendedor que entrega algo pedido (simulação, proposta, documento).
_ANSWER_RE = re.compile(
    r"\b(?:segue|seguem|enviei|mandei|te mand\w*|te envi\w*|anexo|link|pdf|parcela de"
    r"|simulac\w*|simulei|orcament\w*|cotac\w*|cotei|contrato|regulamento|apolice|valores)\b"
    r"|r\$\s?\d"
)
_EVIDENCE_CHARS = 240


def _evidence(text: str) -> str:
    return text if len(text) <= _EVIDENCE_CHARS else text[: _EVIDENCE_CHARS - 1] + "…"


class _Analysis:
    def __init__(self, conversation: ConversationInput) -> None:
        self.conversation = conversation
        self.messages = conversation.messages
        self.playbook = conversation.playbook
        self.labels: dict[int, set[str]] = defaultdict(set)
        self.candidates: list[Candidate] = []
        self.rule_findings: dict[str, Finding] = {}
        self.classifier_findings: dict[str, Finding] = {}
        self.findings: list[Finding] = []
        self.discarded: list[dict[str, object]] = []
        self.layers: list[str] = []

    def severity(self, alert_type: str) -> str:
        return self.playbook.severity_of(alert_type).value

    def finding(
        self,
        alert_type: str,
        index: int | None,
        explanation: str,
        sources: dict[str, object],
        evidence: str | None = None,
    ) -> Finding:
        text = (
            evidence
            if evidence is not None
            else (_evidence(self.messages[index].text) if index is not None else "")
        )
        return Finding(
            type=alert_type,
            category=category_of(alert_type).value,
            severity=self.severity(alert_type),
            message_index=index,
            evidence=text,
            explanation=explanation,
            sources=dict(sources),
        )

    # ------------------------------------------------------------ camadas
    def rules(self, engine: RuleEngine) -> None:
        self.layers.append("regra")
        for hit in engine.evaluate([(m.sender, m.text) for m in self.messages]):
            self.labels[hit.message_index].add(hit.type)
            if hit.type not in RISK_TYPES:
                continue
            candidate_id = f"regra:{hit.message_index}:{hit.type}"
            self.candidates.append(
                Candidate(candidate_id, hit.type, hit.message_index, hit.evidence, "regra")
            )
            finding = self.finding(
                hit.type,
                hit.message_index,
                hit.explanation,
                {"regra": {"regra": hit.rule_id, "descricao": hit.description}},
                evidence=hit.evidence,
            )
            finding.severity = hit.severity.value if hit.severity else finding.severity
            finding.start, finding.end = hit.start, hit.end
            self.rule_findings[candidate_id] = finding

    def classifier(self, model: MessageClassifier) -> None:
        try:
            predictions = model.predict(self.messages)
        except Exception:
            log.exception("classificador_falhou", modelo=model.name)
            return
        self.layers.append("classificador")
        for message, probabilities in zip(self.messages, predictions, strict=False):
            for label, probability in probabilities.items():
                if probability < model.thresholds.get(label, 0.5):
                    continue
                seller_label = label in SELLER_LABELS
                if seller_label != (message.sender is SenderRole.VENDEDOR):
                    continue
                self.labels[message.index].add(label)
                if label not in RISK_TYPES:
                    continue
                source = {"modelo": model.name, "probabilidade": round(probability, 3)}
                rule_id = f"regra:{message.index}:{label}"
                if rule_id in self.rule_findings:
                    self.rule_findings[rule_id].sources["classificador"] = source
                    continue
                candidate_id = f"classificador:{message.index}:{label}"
                self.candidates.append(
                    Candidate(
                        candidate_id, label, message.index, _evidence(message.text), "classificador"
                    )
                )
                finding = self.finding(
                    label, message.index, "Apontado pelo classificador.", {"classificador": source}
                )
                finding.confidence = probability
                self.classifier_findings[candidate_id] = finding

    def injection(self) -> bool:
        found = False
        for message in self.messages:
            if message.sender is SenderRole.CLIENTE and looks_like_injection(message.text):
                found = True
                self.findings.append(
                    self.finding(
                        "tentativa_manipulacao",
                        message.index,
                        "A mensagem tenta dar instruções à análise automática. Ela foi tratada só "
                        "como texto do cliente; a nota não é afetada.",
                        {"metrica": {"heuristica": "instrucao_para_ia"}},
                    )
                )
        return found

    # ------------------------------------------------------------ fusão com o LLM
    def merge_llm(self, report: LLMReport) -> None:
        reviews = {review.id: review for review in report.reviews}
        for candidate_id, finding in self.rule_findings.items():
            review = reviews.get(candidate_id)
            if review is not None:
                finding.sources["llm"] = {"confirmado": review.confirmed, "motivo": review.reason}
                finding.contested = not review.confirmed
        for candidate_id, finding in list(self.classifier_findings.items()):
            review = reviews.get(candidate_id)
            if review is None:
                continue
            if not review.confirmed:
                self.discarded.append(
                    {
                        "tipo": finding.type,
                        "mensagem": finding.message_index,
                        "camada": "classificador",
                        "motivo": "refutado pelo LLM",
                        "detalhe": review.reason,
                    }
                )
                del self.classifier_findings[candidate_id]
            else:
                finding.sources["llm"] = {"confirmado": True, "motivo": review.reason}

        existing = {
            (f.type, f.message_index)
            for f in [*self.rule_findings.values(), *self.classifier_findings.values()]
        }
        for proposal in report.new_findings:
            reason = self._reject(proposal.type, proposal.message_index)
            located = None
            if reason is None:
                located = self._locate(proposal.quote, proposal.message_index)
                if located is None:
                    reason = "evidência não encontrada na conversa"
            if reason is not None or located is None:
                self.discarded.append(
                    {
                        "tipo": proposal.type,
                        "mensagem": proposal.message_index,
                        "camada": "llm",
                        "motivo": reason,
                        "citacao": proposal.quote[:200],
                    }
                )
                continue
            index, start, end = located
            if (proposal.type, index) in existing:
                continue
            existing.add((proposal.type, index))
            text = self.messages[index].text
            finding = self.finding(
                proposal.type,
                index,
                proposal.explanation or "Apontado pelo LLM.",
                {"llm": {"explicacao": proposal.explanation}},
                evidence=text[start:end],
            )
            finding.start, finding.end, finding.confidence = start, end, proposal.confidence
            self.findings.append(finding)
            self.labels[index].add(proposal.type)

    def _reject(self, alert_type: str, index: int) -> str | None:
        if alert_type not in RISK_TYPES:
            return "tipo de achado desconhecido"
        if not 0 <= index < len(self.messages):
            return "mensagem inexistente"
        if self.messages[index].sender is not SenderRole.VENDEDOR:
            return "risco atribuído a uma mensagem que não é do vendedor"
        return None

    def _locate(self, quote: str, index: int) -> tuple[int, int, int] | None:
        for candidate in (index, index - 1, index + 1):
            if (
                0 <= candidate < len(self.messages)
                and self.messages[candidate].sender is SenderRole.VENDEDOR
            ):
                span = ground(quote, self.messages[candidate].text)
                if span is not None:
                    return candidate, span[0], span[1]
        return None

    # ------------------------------------------------------------ heurísticas de oportunidade
    def _next_seller(self, index: int, window: int) -> int | None:
        for message in self.messages[index + 1 : index + 1 + window]:
            if message.sender is SenderRole.VENDEDOR:
                return message.index
            if message.sender is SenderRole.CLIENTE and message.index > index + 1:
                # o cliente mudou de assunto antes de alguém responder
                labels = self.labels.get(message.index, set())
                if labels & {*OBJECTION_TYPES, "pedido_cliente", "sinal_compra"}:
                    return None
        return None

    def heuristic_objections(self) -> list[ObjectionAssessment]:
        result = []
        for index in sorted(self.labels):
            for label in sorted(self.labels[index] & set(OBJECTION_TYPES)):
                answer = self._next_seller(index, window=4)
                if answer is None:
                    handling = "sem_resposta"
                elif self.labels.get(answer, set()) & set(RISK_TYPES):
                    handling = "mal"
                else:
                    handling = "parcial"
                result.append(
                    ObjectionAssessment(
                        message_index=index, type=label, handling=handling, answered_by=answer
                    )
                )
        return result

    def heuristic_requests(self) -> list[RequestAssessment]:
        """Pedidos e se foram atendidos. Cobrar um pedido ainda aberto não abre um pedido novo."""
        result: list[RequestAssessment] = []
        open_request: RequestAssessment | None = None
        for index in sorted(i for i, labels in self.labels.items() if "pedido_cliente" in labels):
            answer = next(
                (
                    m.index
                    for m in self.messages[index + 1 : index + 9]
                    if m.sender is SenderRole.VENDEDOR and _ANSWER_RE.search(fold(m.text))
                ),
                None,
            )
            if open_request is not None and not open_request.answered:
                # cobrança do pedido anterior: se agora foi atendido, o original também foi
                if answer is not None:
                    open_request.answered, open_request.answered_by = True, answer
                continue
            open_request = RequestAssessment(
                message_index=index, answered=answer is not None, answered_by=answer
            )
            result.append(open_request)
        return result

    def heuristic_signals(self) -> list[SignalAssessment]:
        return [
            SignalAssessment(
                message_index=index,
                handled=any(m.sender is SenderRole.VENDEDOR for m in self.messages[index + 1 :]),
            )
            for index in sorted(i for i, labels in self.labels.items() if "sinal_compra" in labels)
        ]


def _valid_objections(
    items: Sequence[ObjectionAssessment], analysis: _Analysis
) -> list[ObjectionAssessment]:
    return [
        item
        for item in items
        if 0 <= item.message_index < len(analysis.messages)
        and analysis.messages[item.message_index].sender is SenderRole.CLIENTE
        and item.type in OBJECTION_TYPES
    ]


def analyze_conversation(
    conversation: ConversationInput,
    *,
    llm: LLMAnalyzer | None = None,
    classifier: MessageClassifier | None = None,
) -> ConversationAnalysis:
    state = _Analysis(conversation)
    engine = RuleEngine(conversation.playbook)
    state.rules(engine)
    if classifier is not None:
        state.classifier(classifier)
    state.layers.append("metrica")
    injection = state.injection()
    metrics = compute_metrics(conversation)

    report: LLMReport | None = None
    llm_error: str | None = None
    if llm is not None:
        try:
            report = llm.analyze(conversation, state.candidates)
        except LLMUnavailable as exc:
            llm_error = str(exc)
        except Exception:
            log.exception("analise_llm_falhou", conversation_id=str(conversation.conversation_id))
            llm_error = "falha inesperada na análise por LLM"
    if report is not None:
        state.layers.append("llm")
        state.merge_llm(report)

    objections = (
        _valid_objections(report.objections, state)
        if report is not None and report.objections is not None
        else state.heuristic_objections()
    )
    requests = (
        report.requests
        if report is not None and report.requests is not None
        else state.heuristic_requests()
    )
    signals = (
        report.signals
        if report is not None and report.signals is not None
        else state.heuristic_signals()
    )
    estimated = {
        "objecoes": report is None or report.objections is None,
        "pedidos": report is None or report.requests is None,
        "sinais": report is None or report.signals is None,
    }
    source = "llm" if report is not None else "metrica"

    findings = [*state.rule_findings.values(), *state.classifier_findings.values(), *state.findings]
    for objection in objections:
        if objection.handling == "sem_resposta":
            findings.append(
                state.finding(
                    "objecao_sem_resposta",
                    objection.message_index,
                    "O cliente levantou uma objeção e não recebeu resposta.",
                    {source: {"objecao": objection.type}},
                )
            )
    for request in requests:
        if not request.answered and 0 <= request.message_index < len(state.messages):
            findings.append(
                state.finding(
                    "pedido_pendente",
                    request.message_index,
                    "O cliente pediu algo e o pedido ficou sem resposta.",
                    {source: {"pedido": request.description or "pedido do cliente"}},
                )
            )
    for signal in signals:
        if not signal.handled and 0 <= signal.message_index < len(state.messages):
            findings.append(
                state.finding(
                    "sinal_compra_ignorado",
                    signal.message_index,
                    "O cliente mostrou intenção de comprar e não teve retorno.",
                    {source: {}},
                )
            )
    limit = conversation.playbook.limite_demora_minutos
    slow = next(((c, s, m) for c, s, m in metrics.replies if m > limit), None)
    if slow is not None:
        findings.append(
            state.finding(
                "demora_resposta",
                slow[1],
                f"Resposta depois de {slow[2]} minutos úteis (limite: {limit}).",
                {"metrica": {"minutos_uteis": slow[2], "mensagem_do_cliente": slow[0]}},
            )
        )
    if metrics.follow_up_missing:
        findings.append(
            state.finding(
                "follow_up_ausente",
                None,
                f"O cliente está em silêncio há {metrics.silence_hours:.0f} h e não houve follow-up.",
                {"metrica": {"horas_em_silencio": round(metrics.silence_hours, 1)}},
            )
        )
        interest = any(
            labels & {"pedido_cliente", "sinal_compra"} for labels in state.labels.values()
        )
        if interest:
            findings.append(
                state.finding(
                    "lead_esfriando",
                    None,
                    "O cliente demonstrou interesse e esfriou sem retomada.",
                    {"metrica": {"horas_em_silencio": round(metrics.silence_hours, 1)}},
                )
            )

    disclosures = engine.disclosures([(m.sender, m.text) for m in conversation.messages])
    score, criteria = score_conversation(
        playbook=conversation.playbook,
        findings=findings,
        objections=objections,
        requests=requests,
        signals=signals,
        disclosures=disclosures,
        metrics=metrics,
        sla_minutes=conversation.response_sla_minutes,
        estimated=estimated,
    )
    findings.sort(key=lambda f: (f.message_index if f.message_index is not None else 10**9, f.type))
    return ConversationAnalysis(
        score=score,
        criteria=criteria,
        findings=findings,
        message_labels={i: sorted(v) for i, v in sorted(state.labels.items()) if v},
        objections=objections,
        requests=requests,
        metrics=metrics,
        layers=state.layers,
        discarded=state.discarded,
        summary=report.summary if report else "",
        suggestion=report.suggestion if report else "",
        sentiment=report.sentiment if report else None,
        stage=report.stage if report else None,
        strengths=report.strengths if report else [],
        improvements=report.improvements if report else [],
        injection_suspected=injection,
        llm_error=llm_error,
        llm=(
            {
                "provider": report.provider,
                "model": report.model,
                "tokens_in": report.tokens_in,
                "tokens_out": report.tokens_out,
                "cached": report.cached,
            }
            if report
            else {}
        ),
    )
