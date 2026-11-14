"""Carregamento de playbooks: arquivos do repositório e playbooks próprios das empresas.

``herda`` junta o playbook com o pai: as regras do pai entram (menos as de ``desativar`` e as
que o filho redefine com o mesmo id), divulgações e objeções são unidas pelo id/tipo, e o resto
(critérios da nota, teto, limites) vale o do filho quando ele define.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from radar.config import get_settings
from radar.playbooks.schema import Playbook

#: Resolve o texto YAML de um playbook pelo slug (ou ``None`` se não existir).
Resolver = Callable[[str], str | None]

_MAX_DEPTH = 5


class PlaybookError(ValueError):
    """Playbook inválido ou inexistente. A mensagem é feita para quem escreveu o YAML."""


def playbooks_dir() -> Path:
    configured = get_settings().playbooks_dir
    if configured is not None:
        return configured
    return Path(__file__).resolve().parents[4] / "playbooks"


def available_playbooks() -> list[str]:
    folder = playbooks_dir()
    return sorted(p.stem for p in folder.glob("*.yaml")) if folder.is_dir() else []


def read_builtin(slug: str) -> str | None:
    if slug not in available_playbooks():
        return None
    return (playbooks_dir() / f"{slug}.yaml").read_text(encoding="utf-8")


def _format_errors(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        where = ".".join(str(p) for p in error["loc"]) or "playbook"
        message = str(error["msg"]).removeprefix("Value error, ")
        parts.append(f"{where}: {message}")
    return "; ".join(parts)


def _validate(data: Any) -> Playbook:
    if not isinstance(data, dict):
        raise PlaybookError("O playbook precisa ser um mapeamento YAML (chave: valor).")
    try:
        return Playbook.model_validate(data)
    except ValidationError as exc:
        raise PlaybookError(f"Playbook inválido — {_format_errors(exc)}") from exc


def _merge(parent: Playbook, child: Playbook) -> Playbook:
    child_ids = {rule.id for rule in child.regras}
    disabled = set(child.desativar)
    rules = [r for r in parent.regras if r.id not in child_ids and r.id not in disabled]
    disclosures = {d.id: d for d in parent.divulgacoes_obrigatorias}
    disclosures.update({d.id: d for d in child.divulgacoes_obrigatorias})
    objections = {o.tipo: o for o in parent.objecoes}
    objections.update({o.tipo: o for o in child.objecoes})
    explicit = child.model_fields_set
    return child.model_copy(
        update={
            "regras": rules + list(child.regras),
            "divulgacoes_obrigatorias": list(disclosures.values()),
            "objecoes": list(objections.values()),
            "boas_praticas": list(dict.fromkeys([*parent.boas_praticas, *child.boas_praticas])),
            "criterios_nota": child.criterios_nota
            if "criterios_nota" in explicit
            else parent.criterios_nota,
            "teto_com_critico": child.teto_com_critico
            if "teto_com_critico" in explicit
            else parent.teto_com_critico,
            "limite_demora_minutos": (
                child.limite_demora_minutos
                if "limite_demora_minutos" in explicit
                else parent.limite_demora_minutos
            ),
            "severidades": {**parent.severidades, **child.severidades},
        }
    )


def parse_playbook(text: str, *, resolver: Resolver | None = None, _depth: int = 0) -> Playbook:
    """Lê, valida e resolve a herança de um playbook escrito em YAML."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PlaybookError(f"YAML inválido: {exc}") from exc
    playbook = _validate(data)
    if playbook.herda is None:
        return playbook
    if _depth >= _MAX_DEPTH:
        raise PlaybookError("Herança de playbooks profunda demais (ou circular).")
    resolve = resolver or read_builtin
    parent_text = resolve(playbook.herda)
    if parent_text is None:
        raise PlaybookError(f"O playbook pai '{playbook.herda}' não foi encontrado.")
    parent = parse_playbook(parent_text, resolver=resolver, _depth=_depth + 1)
    return _merge(parent, playbook)


@cache
def load_playbook(slug: str) -> Playbook:
    """Playbook do repositório (``playbooks/<slug>.yaml``), já com a herança resolvida."""
    text = read_builtin(slug)
    if text is None:
        raise PlaybookError(f"Playbook '{slug}' não encontrado.")
    return parse_playbook(text)


def clear_playbook_cache() -> None:
    load_playbook.cache_clear()
