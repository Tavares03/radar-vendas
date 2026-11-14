"""Schema do playbook (YAML) de um setor ou empresa.

Os nomes dos campos são em português porque quem escreve o playbook é a empresa, não um
programador. Os padrões são expressões regulares comparadas sem diferenciar maiúsculas e acentos.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radar.taxonomy import (
    CLASSIFIER_LABELS,
    DEFAULT_SEVERITY,
    OBJECTION_TYPES,
    SELLER_LABELS,
    SenderRole,
    Severity,
)
from radar.textutil import fold

_SLUG = r"^[a-z0-9][a-z0-9\-_]{0,63}$"


def compile_folded(pattern: str) -> re.Pattern[str]:
    return re.compile(fold(pattern))


def _check_patterns(owner: str, patterns: list[str]) -> None:
    for pattern in patterns:
        try:
            compile_folded(pattern)
        except re.error as exc:
            raise ValueError(f"regex inválida em '{owner}': {pattern!r} ({exc})") from exc


class Rule(BaseModel):
    """Um padrão que, encontrado numa mensagem, gera um rótulo (e, se for risco, um alerta)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_SLUG)
    tipo: str
    descricao: str
    explicacao: str = ""
    severidade: Severity | None = None
    padroes: list[str] = Field(default_factory=list)
    termos: list[str] = Field(default_factory=list)
    excecoes: list[str] = Field(default_factory=list)
    #: Se a regra deve ignorar ocorrências negadas ("não posso garantir…").
    considera_negacao: bool = True

    @field_validator("tipo")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in CLASSIFIER_LABELS:
            raise ValueError(
                f"tipo '{value}' desconhecido; use um de: {', '.join(CLASSIFIER_LABELS)}"
            )
        return value

    @model_validator(mode="after")
    def _patterns(self) -> Rule:
        if not self.padroes and not self.termos:
            raise ValueError(f"a regra '{self.id}' precisa de padroes ou termos")
        _check_patterns(self.id, self.padroes + self.excecoes)
        return self

    @property
    def role(self) -> SenderRole:
        return SenderRole.VENDEDOR if self.tipo in SELLER_LABELS else SenderRole.CLIENTE

    def effective_severity(self, overrides: dict[str, Severity]) -> Severity | None:
        if self.tipo not in SELLER_LABELS:
            return None
        return self.severidade or overrides.get(self.tipo) or DEFAULT_SEVERITY[self.tipo]


class Disclosure(BaseModel):
    """Informação que o vendedor precisa dar (vira o critério de transparência da nota)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_SLUG)
    descricao: str
    padroes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _patterns(self) -> Disclosure:
        _check_patterns(self.id, self.padroes)
        return self


class ObjectionGuide(BaseModel):
    """Como responder bem a uma objeção (usado pelo coach e pela sugestão de resposta)."""

    model_config = ConfigDict(extra="forbid")

    tipo: str
    boas_respostas: list[str] = Field(default_factory=list)
    evitar: list[str] = Field(default_factory=list)

    @field_validator("tipo")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in OBJECTION_TYPES:
            raise ValueError(
                f"objeção '{value}' desconhecida; use um de: {', '.join(OBJECTION_TYPES)}"
            )
        return value


class ScoreWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conformidade: int = Field(30, ge=0)
    objecoes: int = Field(20, ge=0)
    tempo_resposta: int = Field(15, ge=0)
    pedidos: int = Field(15, ge=0)
    transparencia: int = Field(10, ge=0)
    conducao: int = Field(10, ge=0)

    @model_validator(mode="after")
    def _sum(self) -> ScoreWeights:
        total = sum(self.model_dump().values())
        if total != 100:
            raise ValueError(f"os pesos de criterios_nota precisam somar 100 (somam {total})")
        return self


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_SLUG)
    nome: str
    versao: int = Field(1, ge=1)
    descricao: str = ""
    herda: str | None = None
    regras: list[Rule] = Field(default_factory=list)
    #: Ids de regras herdadas que este playbook desliga.
    desativar: list[str] = Field(default_factory=list)
    divulgacoes_obrigatorias: list[Disclosure] = Field(default_factory=list)
    objecoes: list[ObjectionGuide] = Field(default_factory=list)
    boas_praticas: list[str] = Field(default_factory=list)
    criterios_nota: ScoreWeights = Field(default_factory=ScoreWeights)
    #: Nota máxima de uma conversa com alerta crítico.
    teto_com_critico: int = Field(59, ge=0, le=100)
    #: Minutos úteis a partir dos quais uma resposta vira alerta de demora.
    limite_demora_minutos: int = Field(60, ge=1)
    #: Severidade de qualquer tipo de alerta, sobrepondo o padrão.
    severidades: dict[str, Severity] = Field(default_factory=dict)

    @field_validator("severidades")
    @classmethod
    def _known_alerts(cls, value: dict[str, Severity]) -> dict[str, Severity]:
        unknown = set(value) - set(DEFAULT_SEVERITY)
        if unknown:
            raise ValueError(f"tipos de alerta desconhecidos em severidades: {sorted(unknown)}")
        return value

    @model_validator(mode="after")
    def _unique_ids(self) -> Playbook:
        ids = [rule.id for rule in self.regras]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"ids de regra repetidos: {repeated}")
        return self

    def severity_of(self, alert_type: str) -> Severity:
        return self.severidades.get(alert_type) or DEFAULT_SEVERITY[alert_type]
