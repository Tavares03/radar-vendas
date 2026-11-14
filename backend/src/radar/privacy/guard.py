"""Última barreira antes de um texto sair da máquina (LLM em nuvem, webhook…).

Roda a detecção estruturada de novo sobre o texto que vai sair. Se achar CPF, telefone, e-mail ou
outro identificador, recusa: é sinal de que alguém tentou mandar o texto bruto em vez do mascarado.
Nomes e endereços ficam de fora porque dependem de contexto (e a empresa pode ter desligado a
máscara de nomes).
"""

from __future__ import annotations

from radar.privacy.detection import detect_regex
from radar.taxonomy import PiiType

#: Tipos verificados pela trava: os que a regex reconhece sem ambiguidade.
GUARDED_TYPES: frozenset[PiiType] = frozenset(
    {
        PiiType.CPF,
        PiiType.CNPJ,
        PiiType.RG,
        PiiType.TELEFONE,
        PiiType.EMAIL,
        PiiType.CEP,
        PiiType.PIX,
        PiiType.CONTA_BANCARIA,
        PiiType.PLACA,
    }
)


class UnmaskedDataError(ValueError):
    """Texto com dado pessoal sem máscara a caminho de fora da máquina."""


def ensure_masked(text: str) -> None:
    """Levanta :class:`UnmaskedDataError` se o texto ainda tiver dado pessoal estruturado.

    A mensagem do erro só diz os tipos encontrados, nunca os valores.
    """
    found = sorted({span.type.value for span in detect_regex(text) if span.type in GUARDED_TYPES})
    if found:
        raise UnmaskedDataError(
            "Texto com dado pessoal sem máscara não pode sair da máquina: " + ", ".join(found)
        )
