"""Conjunto da demonstração: uma equipe fictícia de consórcio ao longo de oito semanas.

As amostras de ``data/samples/synthetic`` têm um vendedor e uma empresa diferentes em cada
conversa, espalhadas por dois anos: boas para testar a importação, ruins para mostrar o painel
(ninguém tem evolução, o gráfico semanal fica vazio). Aqui as conversas são as do gerador, com
duas mudanças feitas depois de geradas, sem tocar no código que define o dataset:

- o vendedor de cada conversa vira uma das pessoas da equipe (nome no export e no texto);
- as datas são deslocadas em semanas inteiras (o dia da semana e a hora não mudam) para caber
  nas oito semanas antes da data-âncora. Na carga, ``radar seed-demo`` desloca tudo de novo para
  que a âncora seja a semana atual.

Tudo continua sintético: pessoas, empresa, telefones e documentos são inventados.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from radar_synth.banks import load_bank
from radar_synth.generator import generate_conversation
from radar_synth.model import SynthConversation
from radar_synth.writers import export_zip

#: Segunda-feira de referência: as conversas terminam nas oito semanas antes dela.
ANCHOR = date(2026, 11, 16)
WEEKS = 8
COMPANY = "Plano Certo Consórcios"
SECTOR = "consorcio"
MANIFEST = "demo.json"


@dataclass(frozen=True, slots=True)
class TeamMember:
    name: str
    #: ``F`` ou ``M``, para acertar o artigo em "aqui é a Vera".
    gender: str
    #: Peso de cada perfil do gerador (bom, médio, problemático) nas conversas da pessoa.
    profiles: dict[str, float]
    #: Conversas por semana (média).
    pace: float

    @property
    def first_name(self) -> str:
        return self.name.split()[0]


TEAM: tuple[TeamMember, ...] = (
    TeamMember("Rafael Prado", "M", {"bom": 0.8, "medio": 0.2}, 1.2),
    TeamMember("Camila Duarte", "F", {"bom": 0.55, "medio": 0.45}, 1.3),
    TeamMember("Vera Nunes", "F", {"bom": 0.3, "medio": 0.55, "problematico": 0.15}, 1.2),
    TeamMember("Bruno Teixeira", "M", {"bom": 0.15, "medio": 0.5, "problematico": 0.35}, 1.0),
    TeamMember("Diego Farias", "M", {"medio": 0.3, "problematico": 0.7}, 1.0),
)

#: A partir de quantas semanas antes da âncora o treinamento da equipe "faz efeito" (a nota sobe).
COACHING_WEEKS = 3


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    names = sorted(weights)
    return rng.choices(names, weights=[weights[n] for n in names], k=1)[0]


def _profile(rng: random.Random, member: TeamMember, weeks_ago: int) -> str:
    weights = dict(member.profiles)
    if weeks_ago < COACHING_WEEKS and "problematico" in weights:
        # Depois do retorno do gestor, parte das conversas problemáticas vira mediana.
        moved = weights["problematico"] * 0.6
        weights["problematico"] -= moved
        weights["medio"] = weights.get("medio", 0.0) + moved
    return _pick(rng, weights)


def _fold(text: str) -> str:
    """Minúsculas sem acento, com o mesmo comprimento (as posições continuam valendo)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text.lower())


def _swap(text: str, old: str, new: str) -> str:
    """Troca ``old`` por ``new`` como palavra inteira, ignorando acento e maiúsculas.

    O ruído do gerador escreve "consorcio horizonte" e "caio" tanto quanto "Consórcio Horizonte"
    e "Caio"; quem escreveu tudo em minúsculas continua em minúsculas.
    """
    pattern = re.compile(rf"(?<!\w){re.escape(_fold(old))}(?!\w)")
    result, last = [], 0
    for match in pattern.finditer(_fold(text)):
        original = text[match.start() : match.end()]
        result += [text[last : match.start()], new.lower() if original.islower() else new]
        last = match.end()
    return "".join(result) + text[last:]


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(_fold(name))}(?!\w)", _fold(text)) is not None


def _fix_article(text: str, member: TeamMember) -> str:
    """ "aqui é o Vera" → "aqui é a Vera" (o gerador concorda o artigo com a pessoa original)."""
    article = "a" if member.gender == "F" else "o"
    pattern = re.compile(rf"\b([oa])(\s+){re.escape(member.first_name)}\b", re.IGNORECASE)

    def swap(match: re.Match[str]) -> str:
        fixed = article.upper() if match.group(1).isupper() else article
        return f"{fixed}{match.group(2)}{member.first_name}"

    return pattern.sub(swap, text)


def recast(conversation: SynthConversation, member: TeamMember, *, days: int) -> SynthConversation:
    """A mesma conversa com outro vendedor, na empresa da demonstração e ``days`` dias depois."""
    original_display = conversation.seller_display
    original_first = original_display.split()[0]
    shift = timedelta(days=days)
    messages = []
    for message in conversation.messages:
        text = _swap(message.text, conversation.company, COMPANY)
        text = _fix_article(_swap(text, original_first, member.first_name), member)
        messages.append(
            replace(
                message,
                text=text,
                author=member.name if message.author == original_display else message.author,
                timestamp=message.timestamp + shift,
                # As posições das anotações não valem mais depois da troca de nomes.
                pii=[],
            )
        )
    return replace(
        conversation,
        company=COMPANY,
        seller_display=member.name,
        messages=messages,
        exported_at=conversation.exported_at + shift,
    )


def _usable(conversation: SynthConversation, member: TeamMember) -> bool:
    """Evita conversas em que o nome do cliente se confundiria com o do vendedor."""
    seller_first = conversation.seller_display.split()[0]
    customer_first = conversation.customer_display.split()[0]
    return customer_first not in (seller_first, member.first_name)


def _clean(original: SynthConversation, recasted: SynthConversation) -> bool:
    """Depois da troca, não sobrou o vendedor original nem outra empresa do banco no texto."""
    leftovers = [original.seller_display.split()[0]]
    leftovers += [c for c in load_bank(SECTOR).vocab.get("empresa", []) if c != COMPANY]
    return not any(
        _mentions(message.text, name) for message in recasted.messages for name in leftovers
    )


def _weeks_shift(conversation: SynthConversation, target: date) -> int:
    """Dias (múltiplo de 7) para a última mensagem cair na semana de ``target``, antes da âncora."""
    last = conversation.messages[-1].timestamp.date()
    days = 7 * round((target - last).days / 7)
    while last + timedelta(days=days) >= ANCHOR:
        days -= 7
    return days


def build_demo(seed: int = 7) -> list[SynthConversation]:
    """As conversas da demonstração, da mais antiga para a mais recente."""
    rng = random.Random(f"demo:{seed}")
    conversations: list[SynthConversation] = []
    used: set[tuple[str, str]] = set()
    next_seed = 1000
    for weeks_ago in range(WEEKS - 1, -1, -1):
        week_start = ANCHOR - timedelta(weeks=weeks_ago + 1)
        for member in TEAM:
            count = int(member.pace) + (1 if rng.random() < member.pace % 1 else 0)
            for _ in range(count):
                profile = _profile(rng, member, weeks_ago)
                target = week_start + timedelta(days=rng.randrange(0, 6))
                while True:
                    next_seed += 1
                    base = generate_conversation(
                        seed=next_seed, sector=SECTOR, seller_profile=profile
                    )
                    key = (base.customer_display, member.name)
                    if not _usable(base, member) or key in used:
                        continue
                    recasted = recast(base, member, days=_weeks_shift(base, target))
                    if _clean(base, recasted):
                        used.add(key)
                        break
                conversations.append(replace(recasted, id=f"demo-{len(conversations) + 1:02d}"))
    conversations.sort(key=lambda c: c.messages[-1].timestamp)
    return conversations


def write_demo(out: Path, seed: int = 7) -> int:
    """Grava os exports e o ``demo.json`` (equipe, empresa e data-âncora) em ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("demo-*.zip"):
        stale.unlink()
    conversations = build_demo(seed)
    for conversation in conversations:
        _name, data = export_zip(conversation, platform="android", language="pt")
        (out / f"{conversation.id}.zip").write_bytes(data)
    manifest = {
        "ancora": ANCHOR.isoformat(),
        "empresa": COMPANY,
        "playbook": SECTOR,
        "equipe": [member.name for member in TEAM],
        "conversas": len(conversations),
        "gerado_com": f"radar-synth demo --seed {seed}",
    }
    (out / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return len(conversations)
