"""Camada 1 da detecção de dados pessoais: regex, validadores e contexto.

Cada detector propõe trechos candidatos; :func:`resolve_spans` junta os que se sobrepõem (vence o
mais longo e, no empate, o tipo mais específico) e devolve trechos disjuntos, em ordem.

Critério geral: na dúvida entre mascarar demais e de menos, mascarar. Um número *formatado* como
CPF, CNPJ ou telefone é tratado como tal mesmo com dígito verificador errado (erro de digitação
continua sendo dado pessoal). Número *sem formatação* só é mascarado se passar no validador ou se
o texto em volta disser o que ele é ("meu cpf é ...").
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

from radar.privacy.validators import (
    is_valid_cep,
    is_valid_cnpj,
    is_valid_cpf,
    is_valid_email,
    is_valid_phone_br,
    only_digits,
    passes_luhn,
    words,
)
from radar.taxonomy import PiiType

T = PiiType


@dataclass(frozen=True, slots=True)
class PiiSpan:
    """Um dado pessoal encontrado no texto original."""

    type: PiiType
    start: int
    end: int
    #: O trecho original. Fica só em memória: serve para o índice de titulares (HMAC).
    text: str
    #: Camada que encontrou: ``regex``, ``participante`` ou ``ner``.
    source: str = "regex"
    score: float = 1.0

    @property
    def length(self) -> int:
        return self.end - self.start


#: No empate de tamanho, vence o tipo com menor número (mais específico).
_PRIORITY: dict[PiiType, int] = {
    T.CPF: 0,
    T.CNPJ: 0,
    T.EMAIL: 0,
    T.PIX: 0,
    T.TELEFONE: 1,
    T.CEP: 1,
    T.RG: 2,
    T.CONTA_BANCARIA: 2,
    T.PLACA: 2,
    T.ENDERECO: 3,
    T.NOME_PESSOA: 4,
}


def resolve_spans(spans: Iterable[PiiSpan], text: str) -> list[PiiSpan]:
    """Junta trechos sobrepostos num só (a união, para nada ficar descoberto)."""
    ordered = sorted(spans, key=lambda s: (s.start, -s.end))
    resolved: list[PiiSpan] = []
    cluster: list[PiiSpan] = []
    cluster_end = -1

    def flush() -> None:
        if not cluster:
            return
        best = min(cluster, key=lambda s: (-s.length, _PRIORITY[s.type]))
        start = min(s.start for s in cluster)
        end = max(s.end for s in cluster)
        resolved.append(replace(best, start=start, end=end, text=text[start:end]))
        cluster.clear()

    for span in ordered:
        if span.end <= span.start:
            continue
        if cluster and span.start < cluster_end:
            cluster.append(span)
            cluster_end = max(cluster_end, span.end)
            continue
        flush()
        cluster.append(span)
        cluster_end = span.end
    flush()
    return resolved


# ---------------------------------------------------------------- utilidades
def _has_context(text: str, start: int, pattern: re.Pattern[str], window: int = 25) -> bool:
    """O trecho logo antes de ``start`` menciona o que o número é?"""
    return bool(pattern.search(text[max(0, start - window) : start]))


def _span(match: re.Match[str], kind: PiiType, group: int = 0) -> PiiSpan:
    return PiiSpan(kind, match.start(group), match.end(group), match.group(group))


_CPF_CTX = re.compile(r"\bcpf\b", re.IGNORECASE)
_CNPJ_CTX = re.compile(r"\bcnpj\b", re.IGNORECASE)
_CEP_CTX = re.compile(r"\bcep\b", re.IGNORECASE)
_PHONE_CTX = re.compile(
    r"\b(?:tel|telefone|fone|cel|celular|whats(?:app)?|zap|wpp|liga[r]?|n[uú]mero|contato|ramal)\b",
    re.IGNORECASE,
)
_RG_CTX = re.compile(r"\b(?:rg|r\.g\.|identidade|registro geral)(?![\w])", re.IGNORECASE)
_PIX_CTX = re.compile(r"\bpix\b", re.IGNORECASE)
_OTHER_DOC_CTX = re.compile(
    r"\b(?:cpf|cnpj|e-?mail|tel|telefone|cel|celular|fone|whats(?:app)?|zap)\b", re.IGNORECASE
)
_PLATE_CTX = re.compile(r"\bplacas?\b", re.IGNORECASE)


# ---------------------------------------------------------------- documentos
_CPF_RE = re.compile(r"(?<![\w.\-/])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![\w\-/]|\.\d)")


def _detect_cpf(text: str) -> Iterable[PiiSpan]:
    for match in _CPF_RE.finditer(text):
        value = match.group()
        formatted = not value.isdigit()
        if formatted or is_valid_cpf(value) or _has_context(text, match.start(), _CPF_CTX):
            yield _span(match, T.CPF)


_CNPJ_RE = re.compile(
    r"(?<![\w.\-/])[A-Z0-9]{2}\.?[A-Z0-9]{3}\.?[A-Z0-9]{3}/?[A-Z0-9]{4}-?\d{2}(?![\w\-/]|\.\d)",
    re.IGNORECASE,
)


def _detect_cnpj(text: str) -> Iterable[PiiSpan]:
    for match in _CNPJ_RE.finditer(text):
        value = match.group()
        if (
            "/" in value
            or (value.isdigit() and is_valid_cnpj(value))
            or (
                _has_context(text, match.start(), _CNPJ_CTX)
                and sum(c.isdigit() for c in value) >= 8
            )
        ):
            yield _span(match, T.CNPJ)


_PHONE_RE = re.compile(
    r"(?<![\w+])(?:\+\s?55[\s.\-]*|55[\s.\-]+)?(?:\(\s?0?\d{2}\s?\)|0?\d{2})[\s.\-]*"
    r"(?:9[\s.]?)?\d{4}[\s.\-]?\d{4}(?![\d\-])"
)
_MOBILE_NO_DDD_RE = re.compile(r"(?<![\d\-.])9\d{4}[\-\s]\d{4}(?![\d\-])")
_LANDLINE_NO_DDD_RE = re.compile(r"(?<![\d\-.])[2-5]\d{3}-\d{4}(?![\d\-])")


def _detect_phone(text: str) -> Iterable[PiiSpan]:
    for match in _PHONE_RE.finditer(text):
        value = match.group()
        digits = only_digits(value)
        formatted = not value.isdigit() and len(digits) >= 10
        if is_valid_phone_br(value) or (formatted and ("(" in value or "-" in value)):
            yield _span(match, T.TELEFONE)
    for match in _MOBILE_NO_DDD_RE.finditer(text):
        yield _span(match, T.TELEFONE)
    for match in _LANDLINE_NO_DDD_RE.finditer(text):
        if _has_context(text, match.start(), _PHONE_CTX, window=20):
            yield _span(match, T.TELEFONE)


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}")


def _detect_email(text: str) -> Iterable[PiiSpan]:
    for match in _EMAIL_RE.finditer(text):
        value = match.group().rstrip(".")
        if is_valid_email(value):
            yield PiiSpan(T.EMAIL, match.start(), match.start() + len(value), value)


_CEP_RE = re.compile(r"(?<![\d.\-/])\d{5}-\d{3}(?![\d\-])")
_CEP_PLAIN_RE = re.compile(r"(?<![\d.\-/])\d{8}(?![\d\-])")


def _detect_cep(text: str) -> Iterable[PiiSpan]:
    for match in _CEP_RE.finditer(text):
        if is_valid_cep(match.group()):
            yield _span(match, T.CEP)
    for match in _CEP_PLAIN_RE.finditer(text):
        if is_valid_cep(match.group()) and _has_context(text, match.start(), _CEP_CTX, 15):
            yield _span(match, T.CEP)


_RG_FORMATTED_RE = re.compile(r"(?<![\d.\-/])\d{1,2}\.\d{3}\.\d{3}-[\dXx](?![\w\-])")
_RG_CANDIDATE_RE = re.compile(r"(?<![\w.\-/])(?:[A-Za-z]{2}-?)?\d[\d.\-]{3,12}[\dXx](?![\w\-])")


def _detect_rg(text: str) -> Iterable[PiiSpan]:
    for match in _RG_FORMATTED_RE.finditer(text):
        yield _span(match, T.RG)
    for match in _RG_CANDIDATE_RE.finditer(text):
        if sum(c.isdigit() for c in match.group()) < 5:
            continue
        if _has_context(text, match.start(), _RG_CTX, window=20):
            yield _span(match, T.RG)


_PIX_UUID_RE = re.compile(
    r"(?<![\w\-])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\w\-])",
    re.IGNORECASE,
)


def _detect_pix_key(text: str) -> Iterable[PiiSpan]:
    for match in _PIX_UUID_RE.finditer(text):
        yield _span(match, T.PIX)


_NUMBER_LABEL = r"\.?\s*(?:n[º°o]\.?\s*|n\.\s*)?[:=]?\s*"
_AGENCY_RE = re.compile(
    r"\b(?:ag[eê]ncia|ag)" + _NUMBER_LABEL + r"(\d{3,5}(?:-[\dXx])?)(?![\w\-])", re.IGNORECASE
)
_ACCOUNT_RE = re.compile(
    r"(?:\bconta(?:\s+(?:corrente|poupan[cç]a|sal[aá]rio))?|\bc/c|\bcc|\bc\.c\.)"
    + _NUMBER_LABEL
    + r"(\d{4,12}(?:-[\dXx])?|\d{3}-[\dXx])(?![\w\-])",
    re.IGNORECASE,
)


#: Número de cartão (13 a 19 dígitos, em grupos de 4 ou corrido), confirmado pelo Luhn.
_CARD_RE = re.compile(
    r"(?<![\d\-.])(?:\d{4}[\s\-]){3}\d{1,7}(?![\d\-])|(?<![\d\-.])\d{13,19}(?!\d)"
)


def _detect_bank_account(text: str) -> Iterable[PiiSpan]:
    for pattern in (_AGENCY_RE, _ACCOUNT_RE):
        for match in pattern.finditer(text):
            yield _span(match, T.CONTA_BANCARIA, group=1)
    for match in _CARD_RE.finditer(text):
        if passes_luhn(match.group()):
            yield _span(match, T.CONTA_BANCARIA)


_PLATE_RE = re.compile(r"(?<![\w\-])(?:[A-Z]{3}-?\d{4}|[A-Z]{3}\d[A-J]\d{2})(?![\w\-])")
_PLATE_ANYCASE_RE = re.compile(
    r"(?<![\w\-])(?:[A-Z]{3}-?\d{4}|[A-Z]{3}\d[A-J]\d{2})(?![\w\-])", re.IGNORECASE
)


def _detect_plate(text: str) -> Iterable[PiiSpan]:
    for match in _PLATE_RE.finditer(text):
        yield _span(match, T.PLACA)
    for match in _PLATE_ANYCASE_RE.finditer(text):
        if _has_context(text, match.start(), _PLATE_CTX, window=20):
            yield _span(match, T.PLACA)


# ---------------------------------------------------------------- endereço
_STREET_TYPES = (
    r"(?:rua|r\.|avenida|av\.?|alameda|al\.|travessa|tv\.|trav\.|estrada|estr\.|rodovia|rod\."
    r"|pra[cç]a|p[cç]a\.?|largo|viela|beco|vila|servid[aã]o|quadra|qd\.)"
)
_WORD = r"[A-Za-zÀ-ÿ0-9º°'.]+"
_COMPLEMENT = (
    r"(?:\s*[,\-]?\s*(?:apto?\.?|apartamento|ap\.|bloco|bl\.?|casa|sala|conj(?:unto)?\.?|lote"
    r"|lt\.?|andar|fundos)\s*[A-Za-z0-9]{0,5}(?![\w]))*"
)
_ADDRESS_NUMBERED_RE = re.compile(
    r"(?i:\b" + _STREET_TYPES + r")\s+(?:" + _WORD + r"\s+){0,5}?[A-Za-zÀ-ÿ][A-Za-zÀ-ÿº°'.]*"
    r",?\s*(?:(?i:n[º°o]?\.?|n[uú]mero)\s*)?\d{1,5}[A-Za-z]?(?![\w\-/.]\d)" + _COMPLEMENT,
)
_CAP_WORD = r"(?:[A-ZÀ-Ý][\wÀ-ÿ'.]*|d[aoe]s?|\d{1,4})"
_ADDRESS_CONTEXT_RE = re.compile(
    r"(?i:\b(?:endere[cç]o|moro|mora|moramos|resido|reside|fica)\b)[^.\n\d]{0,20}?"
    r"((?i:\b" + _STREET_TYPES + r")\s+[A-ZÀ-Ý][\wÀ-ÿ'.]*(?:\s+" + _CAP_WORD + r")*)"
)
_TRAILING_CONNECTOR_RE = re.compile(r"(?:\s+d[aoe]s?)+$")


def _detect_address(text: str) -> Iterable[PiiSpan]:
    for match in _ADDRESS_NUMBERED_RE.finditer(text):
        value = match.group().rstrip(" ,-")
        yield PiiSpan(T.ENDERECO, match.start(), match.start() + len(value), value)
    for match in _ADDRESS_CONTEXT_RE.finditer(text):
        value = _TRAILING_CONNECTOR_RE.sub("", match.group(1)).rstrip(" ,.")
        start = match.start(1)
        yield PiiSpan(T.ENDERECO, start, start + len(value), value)


# ---------------------------------------------------------------- nomes
#: Palavras que aparecem com maiúscula perto de nomes mas não são nomes (empresa, setor…).
_NOT_NAME_WORDS = words(
    """
    consorcio consorcios loja lojas empresa empresas clinica clinicas imobiliaria seguros seguro
    seguradora corretora banco concessionaria escola faculdade colegio equipe grupo central
    atendimento comercial vendas financeiro suporte setor time agencia administradora rua
    avenida alameda travessa praca estrada rodovia cliente consultor consultora vendedor
    vendedora gerente responsavel bom boa dia tarde noite tudo bem obrigado obrigada sim nao ok
    oi ola senhor senhora doutor doutora
    """
)
_CONNECTORS = frozenset({"da", "de", "do", "das", "dos", "e"})

_NAME = r"[A-ZÀ-Ý][a-zà-ÿ]+(?:[\s](?:(?:d[aoe]s?|e)\s+)?[A-ZÀ-Ý][a-zà-ÿ]+){0,5}"
_NAME_TRIGGER_RE = re.compile(
    r"(?i:\b(?:meu nome [eé]|meu nome eh|me chamo|sou (?:o|a)|aqui [eé] (?:o|a)|aqui eh (?:o|a)"
    r"|fal(?:ar|o|a) com (?:o|a)|chamar (?:o|a))\s+(?:(?:sr|sra|srta|dr|dra|seu|dona)\.?\s+)?)"
    r"(" + _NAME + r")"
)
_HONORIFIC_RE = re.compile(r"\b(?:Sr|Sra|Srta|Dr|Dra|sr|sra|srta|dr|dra)\.?\s+(" + _NAME + r")")


def _fold(text: str) -> str:
    """Minúsculas sem acento, com o mesmo comprimento do texto (posições continuam valendo)."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text.lower())


def _trim_name(value: str) -> str:
    """Corta o nome na primeira palavra que não é nome ("João da Consórcio Bom" → "João")."""
    kept: list[str] = []
    for word in value.split():
        if _fold(word) in _NOT_NAME_WORDS:
            break
        kept.append(word)
    while kept and kept[-1].lower() in _CONNECTORS:
        kept.pop()
    return " ".join(kept)


def _detect_names_by_context(text: str) -> Iterable[PiiSpan]:
    for pattern in (_NAME_TRIGGER_RE, _HONORIFIC_RE):
        for match in pattern.finditer(text):
            name = _trim_name(match.group(1))
            if not name:
                continue
            start = match.start(1)
            yield PiiSpan(T.NOME_PESSOA, start, start + len(name), name)


_NAME_CLEAN_RE = re.compile(r"[^\wÀ-ÿ\s'\-]|[\d_]")


def _name_variants(name: str) -> list[str]:
    """Formas de um nome de participante que vale procurar no texto (já sem acento)."""
    if sum(ch.isdigit() for ch in name) >= 4:
        return []  # é um telefone: a regex de telefone cuida dele
    words = _fold(_NAME_CLEAN_RE.sub(" ", name)).split()
    meaningful = [w for w in words if w not in _NOT_NAME_WORDS and w not in _CONNECTORS]
    if not meaningful:
        return []
    variants: list[str] = []
    if len(words) >= 2:
        variants.append(" ".join(words))
    if len(words[0]) >= 3 and words[0] not in _NOT_NAME_WORDS:
        variants.append(words[0])
    return variants


def detect_known_names(text: str, names: Sequence[str]) -> list[PiiSpan]:
    """Ocorrências dos nomes dos participantes da conversa (sem diferenciar acento e caixa)."""
    variants = sorted(
        {variant for name in names for variant in _name_variants(name)}, key=len, reverse=True
    )
    if not variants or not text:
        return []
    folded = _fold(text)
    spans: list[PiiSpan] = []
    for variant in variants:
        pattern = re.compile(r"(?<![\w])" + re.escape(variant).replace(r"\ ", r"\s+") + r"(?![\w])")
        for match in pattern.finditer(folded):
            spans.append(
                PiiSpan(
                    T.NOME_PESSOA,
                    match.start(),
                    match.end(),
                    text[match.start() : match.end()],
                    source="participante",
                )
            )
    return resolve_spans(spans, text)


# ---------------------------------------------------------------- orquestração
_DETECTORS: tuple[Callable[[str], Iterable[PiiSpan]], ...] = (
    _detect_cpf,
    _detect_cnpj,
    _detect_email,
    _detect_pix_key,
    _detect_phone,
    _detect_cep,
    _detect_rg,
    _detect_bank_account,
    _detect_plate,
    _detect_address,
    _detect_names_by_context,
)
_PIX_RETYPE = frozenset({T.CPF, T.CNPJ, T.EMAIL, T.TELEFONE})


def _apply_pix_context(text: str, spans: list[PiiSpan]) -> list[PiiSpan]:
    """Documento usado como chave PIX ("chave pix: <cpf>") vira PIX."""
    result = []
    for span in spans:
        if span.type in _PIX_RETYPE:
            before = text[max(0, span.start - 25) : span.start]
            pix = None
            for pix in _PIX_CTX.finditer(before):  # noqa: B007  (fica com a última ocorrência)
                pass
            if pix is not None and not _OTHER_DOC_CTX.search(before[pix.end() :]):
                span = replace(span, type=T.PIX)
        result.append(span)
    return result


def detect_regex(text: str) -> list[PiiSpan]:
    """Dados pessoais encontrados por regex, validadores e contexto, sem sobreposição."""
    if not text:
        return []
    candidates = [span for detector in _DETECTORS for span in detector(text)]
    return _apply_pix_context(text, resolve_spans(candidates, text))
