"""Bancos de templates por setor e ato de fala.

Cada arquivo YAML tem um vocabulário (valores para os slots do setor) e atos. Um ato
(``cliente.objecao_preco``, ``vendedor.promessa_indevida``…) tem os rótulos do classificador e
famílias de templates. Uma *família* é uma ideia escrita de várias formas; famílias inteiras vão
para um único split (treino, validação ou teste), para o teste medir generalização e não memória.

Convenções dos templates:

- ``{slot}``: valor do vocabulário do setor ou dado pessoal falso (ver :data:`PII_SLOTS`);
- ``a || b``: pode virar duas mensagens seguidas ("mensagens picotadas"); os rótulos do ato vão
  para a última parte;
- quebras de linha viram mensagens de várias linhas.

``comum.yaml`` vale para todos os setores; o arquivo do setor acrescenta vocabulário, atos e
famílias aos atos comuns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from radar.taxonomy import CLASSIFIER_LABELS, PiiType, SenderRole

SECTORS: tuple[str, ...] = ("consorcio", "seguros", "imobiliaria", "clinica", "generico")

#: Slots preenchidos com dados pessoais falsos (viram anotação de NER com posição).
PII_SLOTS: dict[str, PiiType] = {
    "nome_cliente": PiiType.NOME_PESSOA,
    "primeiro_nome_cliente": PiiType.NOME_PESSOA,
    "nome_vendedor": PiiType.NOME_PESSOA,
    "primeiro_nome_vendedor": PiiType.NOME_PESSOA,
    "nome_terceiro": PiiType.NOME_PESSOA,
    "cpf": PiiType.CPF,
    "cpf_terceiro": PiiType.CPF,
    "cnpj": PiiType.CNPJ,
    "cnpj_empresa": PiiType.CNPJ,
    "rg": PiiType.RG,
    "telefone": PiiType.TELEFONE,
    "telefone_terceiro": PiiType.TELEFONE,
    "telefone_vendedor": PiiType.TELEFONE,
    "email": PiiType.EMAIL,
    "email_vendedor": PiiType.EMAIL,
    "endereco": PiiType.ENDERECO,
    "cep": PiiType.CEP,
    "pix_vendedor": PiiType.PIX,
    "pix_cliente": PiiType.PIX,
    "agencia_cliente": PiiType.CONTA_BANCARIA,
    "conta_cliente": PiiType.CONTA_BANCARIA,
    "agencia_vendedor": PiiType.CONTA_BANCARIA,
    "conta_vendedor": PiiType.CONTA_BANCARIA,
    "cartao": PiiType.CONTA_BANCARIA,
    "placa": PiiType.PLACA,
}

#: Atos que o gerador de roteiros usa; todo setor precisa ter todos.
REQUIRED_ACTS: tuple[str, ...] = (
    "cliente.abertura",
    "cliente.responde_qualificacao",
    "cliente.pergunta_info",
    "cliente.pergunta_garantia",
    "cliente.pede_simulacao",
    "cliente.pede_documento",
    "cliente.cobra_retorno",
    "cliente.objecao_preco",
    "cliente.objecao_confianca",
    "cliente.objecao_prazo",
    "cliente.objecao_vou_pensar",
    "cliente.objecao_concorrente",
    "cliente.objecao_cancelamento",
    "cliente.sinal_compra",
    "cliente.envia_cpf",
    "cliente.envia_email",
    "cliente.envia_telefone",
    "cliente.envia_endereco",
    "cliente.envia_rg",
    "cliente.envia_cnpj",
    "cliente.envia_placa",
    "cliente.envia_cartao",
    "cliente.envia_pix",
    "cliente.envia_dados_completos",
    "cliente.ack",
    "cliente.negacao_dificil",
    "cliente.agradece",
    "cliente.desiste",
    "cliente.retorno_atrasado",
    "cliente.injecao",
    "vendedor.saudacao",
    "vendedor.qualificacao",
    "vendedor.apresentacao",
    "vendedor.divulgacao",
    "vendedor.responde_info",
    "vendedor.envia_simulacao",
    "vendedor.envia_documento",
    "vendedor.negativa_correta",
    "vendedor.pede_dados",
    "vendedor.resposta_preco.bem",
    "vendedor.resposta_preco.parcial",
    "vendedor.resposta_confianca.bem",
    "vendedor.resposta_confianca.parcial",
    "vendedor.resposta_prazo.bem",
    "vendedor.resposta_prazo.parcial",
    "vendedor.resposta_vou_pensar.bem",
    "vendedor.resposta_vou_pensar.parcial",
    "vendedor.resposta_concorrente.bem",
    "vendedor.resposta_concorrente.parcial",
    "vendedor.resposta_cancelamento.bem",
    "vendedor.resposta_cancelamento.parcial",
    "vendedor.fechamento",
    "vendedor.followup",
    "vendedor.despedida",
    "vendedor.ack",
    "vendedor.promessa_indevida",
    "vendedor.informacao_enganosa",
    "vendedor.pressao_abusiva",
    "vendedor.pagamento_fora_canal",
    "vendedor.linguagem_inadequada",
    "vendedor.dados_pessoais_indevidos",
)


class BankError(ValueError):
    """Banco de templates mal formado."""


@dataclass(frozen=True, slots=True)
class Template:
    #: ``<arquivo>.<ato>.<família>``, por exemplo ``consorcio.vendedor.promessa_indevida.data_certa``.
    family: str
    act: str
    text: str


@dataclass(slots=True)
class Act:
    name: str
    role: SenderRole
    labels: tuple[str, ...]
    templates: list[Template] = field(default_factory=list)

    @property
    def families(self) -> list[str]:
        return sorted({t.family for t in self.templates})


@dataclass(slots=True)
class Bank:
    sector: str
    vocab: dict[str, list[str]]
    acts: dict[str, Act]

    @property
    def version_text(self) -> str:
        """Conteúdo canônico (para o hash de versão do dataset)."""
        parts = [f"{k}={'|'.join(v)}" for k, v in sorted(self.vocab.items())]
        for name in sorted(self.acts):
            act = self.acts[name]
            parts += [f"{name}:{','.join(act.labels)}"]
            parts += [f"{t.family}={t.text}" for t in act.templates]
        return "\n".join(parts)


def _read(name: str) -> dict[str, Any]:
    text = resources.files(__package__).joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise BankError(f"{name}.yaml: esperado um mapeamento no topo")
    return data


def expanded_path(origin: str) -> Path:
    """Arquivo com as variantes geradas por LLM para ``origin`` (pode não existir)."""
    return Path(__file__).parent / "expanded" / f"{origin}.yaml"


def _read_expanded(origin: str) -> dict[str, Any]:
    path = expanded_path(origin)
    if not path.exists():
        return {"atos": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Variantes expandidas só acrescentam texto a famílias que já existem.
    return {"atos": data.get("atos") or {}}


def _role(act: str) -> SenderRole:
    prefix = act.split(".", 1)[0]
    if prefix == "cliente":
        return SenderRole.CLIENTE
    if prefix == "vendedor":
        return SenderRole.VENDEDOR
    raise BankError(f"ato '{act}' precisa começar com 'cliente.' ou 'vendedor.'")


def _merge(bank: Bank, origin: str, data: dict[str, Any]) -> None:
    for slot, values in (data.get("vocab") or {}).items():
        bank.vocab[slot] = [str(v) for v in values]
    for name, spec in (data.get("atos") or {}).items():
        labels = tuple(spec.get("rotulos") or ())
        unknown = set(labels) - set(CLASSIFIER_LABELS)
        if unknown:
            raise BankError(f"{origin}: ato {name} com rótulos desconhecidos: {sorted(unknown)}")
        act = bank.acts.get(name)
        if act is None:
            act = bank.acts[name] = Act(name, _role(name), labels)
        elif "rotulos" in spec and labels != act.labels:
            raise BankError(f"{origin}: ato {name} com rótulos diferentes do banco comum")
        for key, variants in (spec.get("familias") or {}).items():
            family = f"{origin}.{name}.{key}"
            if not variants:
                raise BankError(f"{origin}: família {family} vazia")
            act.templates.extend(Template(family, name, str(text).strip()) for text in variants)


@cache
def load_bank(sector: str) -> Bank:
    """Banco comum + o do setor."""
    if sector not in SECTORS:
        raise BankError(f"setor desconhecido: {sector}")
    bank = Bank(sector=sector, vocab={}, acts={})
    for origin in ("comum", sector):
        _merge(bank, origin, _read(origin))
        expanded = _read_expanded(origin)
        known = {t.family for act in bank.acts.values() for t in act.templates}
        for act_name, spec in expanded["atos"].items():
            for key in spec.get("familias") or {}:
                if f"{origin}.{act_name}.{key}" not in known:
                    raise BankError(f"expanded/{origin}.yaml: família inexistente {act_name}.{key}")
        _merge(bank, origin, expanded)
    return bank
