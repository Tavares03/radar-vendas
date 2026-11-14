"""Motor de regras: aplica um playbook às mensagens (texto já mascarado).

Para não transformar "não posso garantir a contemplação" em alerta crítico, uma ocorrência é
ignorada quando, na mesma frase:

- há uma negação nas palavras logo antes dela ("não", "nunca", "ninguém", "nem"…);
- ela está sendo citada ("tem gente que promete…", "quem promete isso…");
- logo depois vem uma refutação ("… não existe", "… é mentira");
- casa com uma das ``excecoes`` da regra.

Em perguntas do cliente a negação não conta: "isso não é golpe não, né?" é desconfiança.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from radar.playbooks.schema import Playbook, Rule, compile_folded
from radar.taxonomy import SenderRole, Severity
from radar.textutil import fold

_NEGATIONS = frozenset({"nao", "nunca", "ninguem", "nem", "jamais", "sem", "n"})
_CITATION_RE = re.compile(
    r"\b(?:promete\w*|prometem|dizem|disse|disseram|falou|falam|fala que|dizer que|tem gente que"
    r"|quem promete|anuncia\w*|cuidado com)\b"
)
_REFUTATION_RE = re.compile(
    r"^\W{0,3}(?:nao existe|e mentira|e golpe|e proibido|nao e verdade|isso nao)"
)
_CLAUSE_BREAK_RE = re.compile(r"[.!?;\n]")
_WORD_RE = re.compile(r"[\w\[\]]+")
_LOOKBACK_WORDS = 6


@dataclass(frozen=True, slots=True)
class RuleHit:
    rule_id: str
    type: str
    #: Só riscos têm severidade; rótulos de cliente (objeção, pedido…) vêm com ``None``.
    severity: Severity | None
    message_index: int
    start: int
    end: int
    evidence: str
    description: str
    explanation: str


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    rule: Rule
    patterns: tuple[re.Pattern[str], ...]
    exceptions: tuple[re.Pattern[str], ...]
    severity: Severity | None


def _whole_words(folded: str, start: int, end: int) -> tuple[int, int]:
    """Estende o trecho até o começo e o fim das palavras ("garantid" → "garantida")."""
    while start > 0 and folded[start - 1].isalnum() and folded[start].isalnum():
        start -= 1
    while end < len(folded) and folded[end].isalnum() and folded[end - 1].isalnum():
        end += 1
    return start, end


def _clause(folded: str, start: int, end: int) -> tuple[int, int]:
    left = max((m.end() for m in _CLAUSE_BREAK_RE.finditer(folded, 0, start)), default=0)
    right_match = _CLAUSE_BREAK_RE.search(folded, end)
    right = right_match.end() if right_match else len(folded)
    return left, right


class RuleEngine:
    def __init__(self, playbook: Playbook) -> None:
        self.playbook = playbook
        compiled = []
        for rule in playbook.regras:
            patterns = [compile_folded(p) for p in rule.padroes]
            patterns += [
                re.compile(r"(?<![\w])" + re.escape(fold(t)).replace(r"\ ", r"\s+") + r"(?![\w])")
                for t in rule.termos
            ]
            compiled.append(
                _CompiledRule(
                    rule=rule,
                    patterns=tuple(patterns),
                    exceptions=tuple(compile_folded(e) for e in rule.excecoes),
                    severity=rule.effective_severity(playbook.severidades),
                )
            )
        self._rules = tuple(compiled)
        self._disclosures = [
            (d.id, tuple(compile_folded(p) for p in d.padroes))
            for d in playbook.divulgacoes_obrigatorias
        ]

    # ------------------------------------------------------------ supressão
    def _suppressed(
        self, compiled: _CompiledRule, folded: str, start: int, end: int, sender: SenderRole
    ) -> bool:
        left, right = _clause(folded, start, end)
        clause = folded[left:right]
        if any(pattern.search(clause) for pattern in compiled.exceptions):
            return True
        if not compiled.rule.considera_negacao:
            return False
        question = clause.rstrip().endswith("?")
        if sender is SenderRole.CLIENTE and question:
            return False
        before = _WORD_RE.findall(folded[left:start])[-_LOOKBACK_WORDS:]
        if any(word in _NEGATIONS for word in before):
            return True
        if _CITATION_RE.search(" ".join(before)):
            return True
        return bool(_REFUTATION_RE.search(folded[end:right]))

    # ------------------------------------------------------------ avaliação
    def evaluate_message(self, text: str, sender: SenderRole, index: int = -1) -> list[RuleHit]:
        """Um acerto por tipo de rótulo (o primeiro na mensagem)."""
        folded = fold(text)
        found: dict[str, RuleHit] = {}
        for compiled in self._rules:
            rule = compiled.rule
            if rule.role is not sender:
                continue
            for pattern in compiled.patterns:
                for match in pattern.finditer(folded):
                    if match.end() == match.start():
                        continue
                    if self._suppressed(compiled, folded, match.start(), match.end(), sender):
                        continue
                    start, end = _whole_words(folded, match.start(), match.end())
                    hit = RuleHit(
                        rule_id=rule.id,
                        type=rule.tipo,
                        severity=compiled.severity,
                        message_index=index,
                        start=start,
                        end=end,
                        evidence=text[start:end],
                        description=rule.descricao,
                        explanation=rule.explicacao or rule.descricao,
                    )
                    current = found.get(rule.tipo)
                    if current is None or hit.start < current.start:
                        found[rule.tipo] = hit
                    break
        return sorted(found.values(), key=lambda h: (h.start, h.type))

    def evaluate(self, messages: Sequence[tuple[SenderRole, str]]) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for index, (sender, text) in enumerate(messages):
            hits.extend(self.evaluate_message(text, sender, index))
        return hits

    def disclosures(self, messages: Sequence[tuple[SenderRole, str]]) -> dict[str, int | None]:
        """Para cada informação obrigatória, a primeira mensagem do vendedor que a traz."""
        result: dict[str, int | None] = {}
        for disclosure_id, patterns in self._disclosures:
            result[disclosure_id] = next(
                (
                    index
                    for index, (sender, text) in enumerate(messages)
                    if sender is SenderRole.VENDEDOR and any(p.search(fold(text)) for p in patterns)
                ),
                None,
            )
        return result
