"""Quem é o vendedor e quem é o cliente numa conversa exportada.

O export só traz nomes (ou telefones). A identificação usa, nesta ordem:

1. o que foi informado no envio (nome ou cadastro do vendedor);
2. o cadastro de vendedores da empresa (nome e apelidos/telefones);
3. o título do export ("Conversa do WhatsApp com Fulano": Fulano é a outra ponta de quem
   exportou — e quem exporta, numa empresa, é o vendedor);
4. o conteúdo (quem oferece × quem pergunta preço).

Cada resultado carrega a confiança e o motivo, para o painel poder pedir confirmação quando a
identificação foi no escuro.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from radar.ingest.whatsapp import ParsedMessage
from radar.privacy.crypto import normalize_identifier
from radar.taxonomy import SenderRole

Confidence = Literal["alta", "media", "baixa"]

_FUZZY_THRESHOLD = 90.0

_SELLER_CUES = re.compile(
    r"\b(?:posso (?:te |lhe )?ajudar|em que posso|aqui [eé] (?:o|a) \w+|sou (?:o|a) \w+ d[aeo]"
    r"|noss[ao]s? (?:empresa|loja|cl[ií]nica|equipe|planos?|produtos?|consultor\w*|condi[cç][oõ]es)"
    r"|segue (?:a|o|em anexo)|fico [aà] disposi[cç][aã]o|qualquer d[uú]vida"
    r"|vou (?:te|lhe) (?:enviar|mandar|passar)|te envio|obrigad[oa] pelo contato"
    r"|condi[cç][aã]o especial|temos (?:planos|op[cç][oõ]es|hor[aá]rios|vagas)"
    r"|posso (?:agendar|reservar|simular)|para fechar|fechamos)",
    re.IGNORECASE,
)
_CUSTOMER_CUES = re.compile(
    r"\b(?:quanto (?:custa|fica|[eé]|sai)|qual (?:o |[eé] o )?(?:valor|pre[cç]o)"
    r"|tenho interesse|gostaria de (?:saber|um or[cç]amento|uma simula[cç][aã]o)"
    r"|queria (?:saber|ver)|vi (?:o|seu|um) an[uú]ncio|voc[eê]s (?:tem|t[eê]m|fazem|aceitam|trabalham)"
    r"|me (?:passa|manda|envia)|pode me (?:enviar|mandar|passar)|vou pensar"
    r"|(?:t[aá]|est[aá]|achei) (?:muito )?caro|preciso falar com (?:meu|minha))",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SellerRef:
    """O mínimo do cadastro de um vendedor para reconhecê-lo num export."""

    id: uuid.UUID
    display_name: str
    aliases: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return (self.display_name, *self.aliases)


@dataclass(frozen=True, slots=True)
class ParticipantInfo:
    author: str
    role: SenderRole
    seller_id: uuid.UUID | None = None
    confidence: Confidence = "alta"
    reason: str = ""


def names_match(left: str, right: str) -> bool:
    """Mesmo nome ou telefone, tolerando acento, caixa, DDI e pequenas variações."""
    a, b = normalize_identifier(left), normalize_identifier(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        # Telefones: compara pelos últimos 8 dígitos (com ou sem DDD e nono dígito).
        return a.isdigit() and b.isdigit() and len(a) >= 8 and len(b) >= 8 and a[-8:] == b[-8:]
    if min(len(a), len(b)) < 4:
        return False
    return fuzz.token_set_ratio(a, b) >= _FUZZY_THRESHOLD and (
        # token_set_ratio dá 100 para "carla" × "carla mendes"; exigimos o primeiro nome igual.
        a.split()[0] == b.split()[0]
    )


def _match_seller(author: str, sellers: Sequence[SellerRef]) -> SellerRef | None:
    for seller in sellers:
        if any(names_match(author, name) for name in seller.names):
            return seller
    return None


def _content_scores(authors: Sequence[str], messages: Sequence[ParsedMessage]) -> dict[str, int]:
    scores = dict.fromkeys(authors, 0)
    for message in messages:
        if message.author not in scores or not message.text:
            continue
        scores[message.author] += len(_SELLER_CUES.findall(message.text))
        scores[message.author] -= len(_CUSTOMER_CUES.findall(message.text))
    return scores


def _guess_seller(
    authors: Sequence[str],
    *,
    chat_title: str | None,
    messages: Sequence[ParsedMessage],
) -> tuple[str, Confidence, str]:
    """Escolhe o autor mais provável de ser o vendedor quando nada o identifica."""
    if chat_title:
        counterpart = [a for a in authors if names_match(a, chat_title)]
        others = [a for a in authors if a not in counterpart]
        if counterpart and len(others) == 1:
            return others[0], "media", "o export tem o nome do cliente no título"

    scores = _content_scores(authors, messages)
    ranked = sorted(authors, key=lambda a: scores[a], reverse=True)
    if len(ranked) >= 2 and scores[ranked[0]] - scores[ranked[1]] >= 2:
        return ranked[0], "media", "o conteúdo das mensagens indica quem está vendendo"
    if len(ranked) == 1:
        return ranked[0], "baixa", "a conversa só tem mensagens de uma pessoa"

    # Sem nenhuma pista: em atendimento receptivo o cliente fala primeiro.
    first = next((m.author for m in messages if m.author in authors), authors[0])
    seller = next((a for a in authors if a != first), authors[0])
    return seller, "baixa", "sem pistas; assumi que o cliente mandou a primeira mensagem"


def identify_participants(
    authors: Sequence[str],
    *,
    sellers: Sequence[SellerRef] = (),
    seller_hint: str | None = None,
    forced_seller: SellerRef | None = None,
    chat_title: str | None = None,
    messages: Sequence[ParsedMessage] = (),
) -> dict[str, ParticipantInfo]:
    """Atribui um papel a cada autor do export.

    ``seller_hint`` é o nome do vendedor como aparece no arquivo, informado no envio.
    ``forced_seller`` é o cadastro escolhido no envio: a conversa é dele, apareça como aparecer.
    """
    if not authors:
        return {}
    result: dict[str, ParticipantInfo] = {}

    # 1) Indicação explícita de quem enviou.
    if seller_hint:
        for author in authors:
            if names_match(author, seller_hint):
                matched = forced_seller or _match_seller(author, sellers)
                result[author] = ParticipantInfo(
                    author,
                    SenderRole.VENDEDOR,
                    matched.id if matched else None,
                    "alta",
                    "nome do vendedor informado no envio",
                )

    # 2) Cadastro de vendedores.
    candidates = [forced_seller] if forced_seller else list(sellers)
    for author in authors:
        if author in result:
            continue
        matched = _match_seller(author, [c for c in candidates if c is not None])
        if matched is not None:
            result[author] = ParticipantInfo(
                author, SenderRole.VENDEDOR, matched.id, "alta", "nome cadastrado como vendedor"
            )

    # 3) Ninguém reconhecido: título do export e conteúdo.
    if not result:
        guessed, confidence, reason = _guess_seller(
            authors, chat_title=chat_title, messages=messages
        )
        result[guessed] = ParticipantInfo(
            guessed,
            SenderRole.VENDEDOR,
            forced_seller.id if forced_seller else None,
            "alta" if forced_seller and confidence == "media" else confidence,
            reason,
        )

    # 4) Todos os demais são clientes.
    seller_confidences = [info.confidence for info in result.values()]
    customer_confidence: Confidence = (
        "baixa"
        if "baixa" in seller_confidences
        else "media"
        if "media" in seller_confidences
        else "alta"
    )
    for author in authors:
        if author not in result:
            result[author] = ParticipantInfo(
                author, SenderRole.CLIENTE, None, customer_confidence, "não é vendedor"
            )
    return result
