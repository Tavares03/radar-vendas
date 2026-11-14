"""Ruído de WhatsApp: abreviações, gírias, acentos esquecidos, erros de digitação e emojis.

Tudo aqui opera só em trechos *literais* do template. Os dados pessoais (slots) passam por fora,
então as posições anotadas continuam exatas.
"""

from __future__ import annotations

import random
import re
import unicodedata

#: (padrão, substitutos). Ordem importa: expressões de várias palavras primeiro.
_ABBREVIATIONS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(rf"(?<![\wÀ-ÿ]){pattern}(?![\wÀ-ÿ])", re.IGNORECASE), options)
    for pattern, options in (
        (r"tudo bem", ("td bem", "tdb")),
        (r"por favor", ("pfv", "pf", "por fvr")),
        (r"de novo", ("dnv",)),
        (r"por que", ("pq",)),
        (r"você", ("vc",)),
        (r"voce", ("vc",)),
        (r"vocês", ("vcs",)),
        (r"também", ("tb", "tbm")),
        (r"porque", ("pq",)),
        (r"beleza", ("blz",)),
        (r"obrigad[oa]", ("obg", "brigado")),
        (r"para", ("pra",)),
        (r"está", ("tá", "ta")),
        (r"estou", ("tô", "to")),
        (r"hoje", ("hj",)),
        (r"quando", ("qnd", "qdo")),
        (r"mensagem", ("msg",)),
        (r"valeu", ("vlw",)),
        (r"mesmo", ("msm",)),
        (r"agora", ("agr",)),
        (r"não", ("nao", "n")),
        (r"qualquer", ("qlqr", "qualqr")),
        (r"cadê", ("cade",)),
        (r"certeza", ("ctz",)),
        (r"blz", ("blz",)),
    )
)

EMOJIS = ("😊", "👍", "🙏", "😅", "😉", "🤔", "😍", "👏", "🙌", "😂", "😕", "✅")
LAUGHS = ("kkk", "kkkkk", "rs", "rsrs", "hahaha")
FILLERS = ("então, ", "é... ", "olha, ", "tipo assim, ", "bom, ", "ó, ")


def abbreviate(text: str, rng: random.Random, *, probability: float) -> str:
    for pattern, options in _ABBREVIATIONS:

        def _swap(match: re.Match[str], options: tuple[str, ...] = options) -> str:
            return rng.choice(options) if rng.random() < probability else match.group()

        text = pattern.sub(_swap, text)
    return text


def _strip_accents(word: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", word) if not unicodedata.combining(ch))


def strip_some_accents(text: str, rng: random.Random, *, probability: float) -> str:
    return re.sub(
        r"[\wÀ-ÿ]+",
        lambda m: _strip_accents(m.group()) if rng.random() < probability else m.group(),
        text,
    )


def add_typo(word: str, rng: random.Random) -> str:
    """Um erro de digitação plausível que preserva a primeira letra."""
    if len(word) < 4:
        return word
    position = rng.randrange(1, len(word) - 1)
    kind = rng.choice(("troca", "falta", "dobra"))
    if kind == "troca":
        chars = list(word)
        chars[position], chars[position + 1] = chars[position + 1], chars[position]
        return "".join(chars)
    if kind == "falta":
        return word[:position] + word[position + 1 :]
    return word[:position] + word[position] + word[position:]


def _typos(text: str, rng: random.Random, probability: float) -> str:
    return re.sub(
        r"[A-Za-zÀ-ÿ]{5,}",
        lambda m: add_typo(m.group(), rng) if rng.random() < probability else m.group(),
        text,
    )


_LEVELS = {
    # nível: (abreviação, acento, erro de digitação, tirar vírgula)
    1: (0.25, 0.0, 0.0, 0.0),
    2: (0.6, 0.25, 0.02, 0.3),
    3: (0.9, 0.5, 0.06, 0.7),
}


def apply_noise(text: str, rng: random.Random, *, level: int, lowercase: bool = False) -> str:
    """Aplica ruído a um trecho literal. ``level`` 0 devolve o texto como está."""
    if level <= 0 or not text:
        return text
    p_abbrev, p_accent, p_typo, p_comma = _LEVELS[min(level, 3)]
    text = abbreviate(text, rng, probability=p_abbrev)
    if p_accent:
        text = strip_some_accents(text, rng, probability=p_accent)
    if p_typo:
        text = _typos(text, rng, p_typo)
    if p_comma and rng.random() < p_comma:
        text = text.replace(",", "")
    if lowercase:
        text = text.lower()
    return text


def message_suffix(rng: random.Random, level: int) -> str:
    """Emoji ou risada no fim da mensagem (mais comum quanto mais informal)."""
    roll = rng.random()
    if roll < 0.08 * level:
        return " " + rng.choice(LAUGHS)
    if roll < 0.2 * level:
        return " " + rng.choice(EMOJIS)
    return ""


def drop_final_period(text: str, rng: random.Random, level: int) -> str:
    if level and text.endswith(".") and rng.random() < 0.3 * level:
        return text[:-1]
    return text
