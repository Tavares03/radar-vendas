"""Defesas da própria análise: tentativa de manipular o LLM e verificação de evidência."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from radar.textutil import fold

#: Instruções dirigidas à IA no meio da conversa. O texto do cliente é dado, nunca instrução.
_INJECTION_RE = re.compile(
    r"ignore (?:as |todas as |todas )?(?:instruc|regras|orientac)"
    r"|(?:esqueca|desconsidere) (?:o |as |os |todas as )?(?:playbook|regras|instruc)"
    r"|instruc\w* (?:para|pra) (?:a |o )?(?:ia|sistema|modelo|assistente)"
    r"|\[(?:sistema|system|instrucao)\]|###\s*instruc"
    r"|(?:assistente|modelo de ia|inteligencia artificial|chatgpt|\bia\b),? (?:se voce|responda|classifique|marque|ignore|esqueca)"
    r"|(?:de|da|atribua) nota (?:100|10|maxima)"
    r"|classifique (?:esta|a) conversa|marque tudo como|nao (?:gere|aponte|crie) (?:alertas|riscos)"
    r"|registre que o vendedor|considere que o vendedor|diga que o vendedor"
    r"|\bprompt\b|jailbreak"
)


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(fold(text)))


def ground(quote: str, text: str, *, threshold: float = 90.0) -> tuple[int, int] | None:
    """Onde a citação aparece no texto (exata ou quase), ou ``None`` se não aparece."""
    needle, haystack = fold(quote).strip(), fold(text)
    if len(needle) < 6:
        return None
    position = haystack.find(needle)
    if position >= 0:
        return position, position + len(needle)
    alignment = fuzz.partial_ratio_alignment(needle, haystack)
    if alignment is None or alignment.score < threshold:
        return None
    return alignment.dest_start, alignment.dest_end
