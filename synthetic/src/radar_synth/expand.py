"""Expansão de variedade: um LLM gratuito reescreve cada família de templates de outros jeitos.

As novas variantes entram na *mesma família* (logo, no mesmo split) e são validadas antes de
entrar no banco: mesmos slots dos originais, nenhum dado pessoal literal, nada repetido e, nos
atos de negação, a negação precisa continuar lá. O resultado fica versionado em
``banks/expanded/<origem>.yaml`` e muda a versão do dataset.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from radar.privacy.detection import detect_regex
from radar.taxonomy import label_pt
from radar_synth.banks import Act, Bank, expanded_path
from radar_synth.llm import ChatClient, LLMError, parse_json

_SLOT_RE = re.compile(r"\{(\w+)\}")
_NEGATION_RE = re.compile(r"\b(?:não|nao|nunca|ninguém|ninguem|nem|sem|jamais)\b", re.IGNORECASE)
_NEGATION_ACTS = frozenset({"vendedor.negativa_correta", "cliente.negacao_dificil"})

SYSTEM_PROMPT = (
    "Você escreve mensagens curtas de WhatsApp em português do Brasil, como vendedores e clientes "
    "reais escrevem, para um dataset sintético de treino. Varie vocabulário, ordem e tom, mas "
    "mantenha exatamente a mesma intenção. Nunca escreva nomes, telefones, documentos, e-mails ou "
    "endereços: use só os marcadores entre chaves que aparecem nos exemplos. Responda apenas com "
    'JSON no formato {"variantes": ["...", "..."]}.'
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def validate_variant(candidate: str, originals: list[str], act_name: str) -> str | None:
    """``None`` se a variante pode entrar no banco; senão, o motivo da recusa."""
    text = candidate.strip()
    if not 4 <= len(text) <= 240:
        return "tamanho fora do limite"
    if any(_normalize(text) == _normalize(o) for o in originals):
        return "repete um exemplo"
    slots = Counter(_SLOT_RE.findall(text))
    if all(slots != Counter(_SLOT_RE.findall(o)) for o in originals):
        return "marcadores diferentes dos exemplos"
    literal = _SLOT_RE.sub("…", text)
    if "{" in literal or "}" in literal:
        return "chave solta"
    if detect_regex(literal):
        return "dado pessoal literal"
    if act_name in _NEGATION_ACTS and not _NEGATION_RE.search(literal):
        return "perdeu a negação"
    return None


def _prompt(bank: Bank, act: Act, examples: list[str], count: int) -> str:
    labels = ", ".join(label_pt(label) for label in act.labels) or "nenhum (mensagem neutra)"
    role = "cliente" if act.role.value == "cliente" else "vendedor"
    lines = "\n".join(f"- {example}" for example in examples)
    return (
        f"Setor: {bank.sector}\nQuem fala: {role}\nAto: {act.name}\nRótulos: {labels}\n\n"
        f"Exemplos (todos com a mesma intenção):\n{lines}\n\n"
        f"Escreva {count} novas formas de dizer a MESMA coisa. Mantenha os marcadores entre "
        "chaves exatamente como estão nos exemplos (nem mais, nem menos). '||' separa partes que "
        "a pessoa mandaria em mensagens seguidas; use se fizer sentido."
    )


def expand_family(
    client: ChatClient, bank: Bank, act: Act, family: str, *, count: int
) -> list[str]:
    """Pede ``count`` variantes ao LLM e devolve só as válidas."""
    examples = [t.text for t in act.templates if t.family == family]
    answer = parse_json(client.complete(SYSTEM_PROMPT, _prompt(bank, act, examples, count)))
    candidates = answer.get("variantes", []) if isinstance(answer, dict) else []
    accepted: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        if validate_variant(candidate, examples + accepted, act.name) is None:
            accepted.append(candidate.strip())
    return accepted[:count]


def expand_bank(
    client: ChatClient,
    bank: Bank,
    *,
    origin: str,
    per_family: int = 3,
    max_families: int | None = None,
) -> dict[str, dict[str, list[str]]]:
    """Variantes novas para as famílias de ``origin`` (``comum`` ou o setor): ato → família → lista."""
    result: dict[str, dict[str, list[str]]] = {}
    done = 0
    for act in bank.acts.values():
        for family in act.families:
            if family.split(".", 1)[0] != origin:
                continue
            if max_families is not None and done >= max_families:
                return result
            try:
                variants = expand_family(client, bank, act, family, count=per_family)
            except LLMError:
                continue
            done += 1
            if variants:
                key = family.rsplit(".", 1)[1]
                result.setdefault(act.name, {})[key] = variants
    return result


def save_expansions(origin: str, expansions: dict[str, dict[str, list[str]]]) -> Path:
    """Acrescenta as variantes ao arquivo ``banks/expanded/<origem>.yaml`` (sem duplicar)."""
    path = expanded_path(origin)
    current: dict[str, Any] = {}
    if path.exists():
        current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    acts = current.setdefault("atos", {})
    for act_name, families in expansions.items():
        stored = acts.setdefault(act_name, {}).setdefault("familias", {})
        for key, variants in families.items():
            existing = stored.setdefault(key, [])
            seen = {_normalize(v) for v in existing}
            for variant in variants:
                if _normalize(variant) not in seen:
                    existing.append(variant)
                    seen.add(_normalize(variant))
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Variantes geradas por LLM e validadas automaticamente para '{origin}'.\n"
        "# Revise por amostragem (radar-synth review). Mesmo id de família = mesmo split.\n"
    )
    path.write_text(
        header + yaml.safe_dump(current, allow_unicode=True, sort_keys=True, width=100),
        encoding="utf-8",
        newline="\n",
    )
    return path
