"""Montagem do dataset: splits sem vazamento de template, arquivos JSONL e manifesto.

**Splits por família.** Cada família de templates (uma ideia escrita de vários jeitos) vai
inteira para o treino ou para a parte reservada (validação e teste). Assim o teste mede se o
modelo generaliza para frases que nunca viu, e não se decorou os templates. A separação é feita
por grupo (arquivo de origem + ato): grupos com menos de três famílias ficam só no treino.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from radar_synth import __version__
from radar_synth.banks import SECTORS, load_bank
from radar_synth.generator import generate_conversation
from radar_synth.model import SynthConversation
from radar_synth.writers import export_zip

SPLITS: tuple[str, ...] = ("train", "validation", "test")
#: Versão do formato dos arquivos. Muda quando campos mudam de sentido.
SCHEMA_VERSION = "1.0"
DEFAULT_SIZES: dict[str, int] = {"train": 3000, "validation": 500, "test": 500}
_EXPORT_FORMATS = (("android", "pt"), ("ios", "pt"), ("android", "en"), ("ios", "en"))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@cache
def family_splits() -> dict[str, frozenset[str]]:
    """Família → splits em que ela pode aparecer."""
    groups: dict[tuple[str, str], set[str]] = {}
    for sector in SECTORS:
        for act in load_bank(sector).acts.values():
            for family in act.families:
                origin = family.split(".", 1)[0]
                groups.setdefault((origin, act.name), set()).add(family)

    assignment: dict[str, frozenset[str]] = {}
    for families in groups.values():
        ordered = sorted(families, key=_hash)
        if len(ordered) < 3:
            assignment.update({f: frozenset({"train"}) for f in ordered})
            continue
        held = max(1, round(len(ordered) * 0.3))
        for family in ordered[held:]:
            assignment[family] = frozenset({"train"})
        reserved = ordered[:held]
        if len(reserved) == 1:
            assignment[reserved[0]] = frozenset({"validation", "test"})
        else:
            half = len(reserved) // 2
            for family in reserved[:half]:
                assignment[family] = frozenset({"validation"})
            for family in reserved[half:]:
                assignment[family] = frozenset({"test"})
    return assignment


#: Módulos cujo código decide o conteúdo do dataset.
_GENERATOR_MODULES = ("generator", "render", "noise", "fake", "profiles", "challenge", "model")


def generator_sources() -> str:
    """Código-fonte do gerador (entra no hash da versão do dataset)."""
    package = resources.files("radar_synth")
    texts = [package.joinpath(f"{n}.py").read_text(encoding="utf-8") for n in _GENERATOR_MODULES]
    texts.append(package.joinpath("challenge.yaml").read_text(encoding="utf-8"))
    return "\n".join(texts)


@cache
def dataset_version() -> str:
    """``<esquema>+<hash>``: muda quando o código do gerador ou qualquer banco muda."""
    content = "\n".join(
        [__version__, generator_sources(), *(load_bank(s).version_text for s in SECTORS)]
    )
    return f"{SCHEMA_VERSION}+{_hash(content)[:10]}"


def _conversation_seed(seed: int, split: str, index: int) -> int:
    return int(_hash(f"{seed}:{split}:{index}")[:12], 16)


def build_dataset(
    *,
    sizes: dict[str, int] | None = None,
    seed: int = 20261113,
    sectors: Sequence[str] = SECTORS,
) -> list[SynthConversation]:
    """Gera as conversas de cada split, distribuídas igualmente entre os setores."""
    sizes = sizes or DEFAULT_SIZES
    assignment = family_splits()
    conversations: list[SynthConversation] = []
    for split in SPLITS:

        def allowed(family: str, split: str = split) -> bool:
            return split in assignment[family]

        for index in range(sizes.get(split, 0)):
            sector = sectors[index % len(sectors)]
            conversations.append(
                generate_conversation(
                    seed=_conversation_seed(seed, split, index),
                    sector=sector,
                    split=split,
                    allow_family=allowed,
                    conversation_id=f"{split}-{index:05d}",
                )
            )
    return conversations


# ---------------------------------------------------------------- arquivos
def message_rows(conversation: SynthConversation) -> Iterable[dict[str, Any]]:
    """Linhas do classificador de mensagens (uma por mensagem)."""
    for message in conversation.messages:
        yield {
            "id": f"{conversation.id}#{message.index}",
            "conversation_id": conversation.id,
            "split": conversation.split,
            "sector": conversation.sector,
            "sender": message.sender,
            "kind": message.kind,
            "stage": message.stage,
            "text": message.text,
            "labels": message.labels,
            "family": message.family,
        }


def ner_rows(conversation: SynthConversation) -> Iterable[dict[str, Any]]:
    """Linhas de NER: o texto e as entidades com posição (inclui mensagens sem entidade)."""
    for message in conversation.messages:
        yield {
            "id": f"{conversation.id}#{message.index}",
            "split": conversation.split,
            "sector": conversation.sector,
            "text": message.text,
            "entities": [
                {"type": p.type, "start": p.start, "end": p.end, "value": p.value}
                for p in message.pii
            ],
        }


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _stats(conversations: Sequence[SynthConversation]) -> dict[str, Any]:
    by_split: dict[str, list[SynthConversation]] = {}
    for conversation in conversations:
        by_split.setdefault(conversation.split, []).append(conversation)

    def count(values: Iterable[str]) -> dict[str, int]:
        return dict(sorted(Counter(values).items()))

    return {
        "conversations": {s: len(v) for s, v in by_split.items()},
        "messages": {s: sum(len(c.messages) for c in v) for s, v in by_split.items()},
        "labels": {
            s: count(label for c in v for m in c.messages for label in m.labels)
            for s, v in by_split.items()
        },
        "pii": {
            s: count(p.type for c in v for m in c.messages for p in m.pii)
            for s, v in by_split.items()
        },
        "alerts": {
            s: count(a.type for c in v for a in c.expected_alerts) for s, v in by_split.items()
        },
        "sectors": {s: count(c.sector for c in v) for s, v in by_split.items()},
        "seller_profiles": {s: count(c.seller_profile for c in v) for s, v in by_split.items()},
        "outcomes": {s: count(c.outcome for c in v) for s, v in by_split.items()},
        "audio_messages": {
            s: sum(1 for c in v for m in c.messages if m.kind == "audio")
            for s, v in by_split.items()
        },
    }


def write_dataset(
    conversations: Sequence[SynthConversation],
    out_dir: Path,
    *,
    exports_per_split: int = 0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Grava o dataset em ``out_dir`` e devolve o manifesto (também salvo em ``manifest.json``)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    splits = sorted({c.split for c in conversations}, key=lambda s: (s not in SPLITS, s))
    for split in splits:
        subset = [c for c in conversations if c.split == split]
        _write_jsonl(out_dir / "conversations" / f"{split}.jsonl", (c.to_dict() for c in subset))
        _write_jsonl(
            out_dir / "messages" / f"{split}.jsonl", (r for c in subset for r in message_rows(c))
        )
        _write_jsonl(out_dir / "ner" / f"{split}.jsonl", (r for c in subset for r in ner_rows(c)))
        for index, conversation in enumerate(subset[:exports_per_split]):
            platform, language = _EXPORT_FORMATS[index % len(_EXPORT_FORMATS)]
            _, data = export_zip(conversation, platform=platform, language=language)
            target = out_dir / "exports" / split / f"{conversation.id}-{platform}-{language}.zip"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    files = {
        path.relative_to(out_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(out_dir.rglob("*.jsonl"))
    }
    manifest: dict[str, Any] = {
        "name": "radar-vendas-conversas-sinteticas",
        "version": dataset_version(),
        "generator_version": __version__,
        "seed": seed,
        "splits": list(splits),
        **_stats(conversations),
        "files": files,
        "license": "CC-BY-4.0",
        "notice": "Dados 100% sintéticos. Nenhuma pessoa ou empresa real.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
