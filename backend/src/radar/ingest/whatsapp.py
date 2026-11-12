"""Parser do export de conversa do WhatsApp (o ``.txt`` de "Exportar conversa").

Formatos aceitos (texto real dos aplicativos; os exemplos aqui são inventados):

- Android:  ``25/12/2023 14:32 - Carla: Bom dia!``  (também ``25/12/23, 14:32 - …``)
- iOS:      ``[25/12/2023, 14:32:15] Carla: Bom dia!``
- Inglês:   ``12/25/23, 2:32 PM - Carla: Good morning``  e  ``[12/25/23, 2:32:15 PM] Carla: …``
- Datas com ``/``, ``.`` ou ``-``; ano com 2 ou 4 dígitos; ``AAAA-MM-DD``.

O parser é puro: recebe texto, devolve :class:`ParsedChat`. Os horários saem **sem fuso** (é o
horário local do aparelho que exportou); quem ingere aplica o fuso da empresa.

Regra de ouro das datas: o export não diz se ``03/04`` é 3 de abril ou 4 de março. A ordem é
inferida olhando o arquivo inteiro (valores acima de 12, ordem cronológica, amplitude do
período). Quando nem assim dá para saber, vale o padrão brasileiro (dia/mês), e a dúvida fica
registrada em ``date_order_ambiguous`` e nos avisos — nunca é resolvida em silêncio.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from radar.taxonomy import MessageKind

Platform = Literal["android", "ios"]
DateOrder = Literal["dmy", "mdy", "ymd"]

#: Marcas invisíveis de direção e BOM que o WhatsApp espalha pelo arquivo.
_MARKS = "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"
_MARKS_RE = re.compile(f"[{_MARKS}]")

_HEADER_RE = re.compile(
    rf"""^[{_MARKS}]*
    (?P<bracket>\[)?
    (?P<d1>\d{{1,4}})[/.\-](?P<d2>\d{{1,2}})[/.\-](?P<d3>\d{{1,4}})
    ,?\s+
    (?P<h>\d{{1,2}})[:.](?P<mi>\d{{2}})(?:[:.](?P<s>\d{{2}}))?
    (?:\s*(?P<ampm>[AaPp])\.?\s?[Mm]\.?)?
    (?(bracket)\]|\s+-)
    (?:\s(?P<rest>.*))?$""",
    re.VERBOSE | re.DOTALL,
)

_MAX_AUTHOR_LENGTH = 60

# ---------------------------------------------------------------- padrões de conteúdo
_AUDIO_EXT = frozenset({"opus", "ogg", "oga", "m4a", "mp3", "aac", "amr", "wav", "weba"})
_IMAGE_EXT = frozenset({"jpg", "jpeg", "png", "gif", "heic", "bmp"})
_VIDEO_EXT = frozenset({"mp4", "3gp", "mov", "mkv", "avi", "webm"})
_STICKER_EXT = frozenset({"webp", "was"})
_CONTACT_EXT = frozenset({"vcf"})

_ANDROID_ATTACHMENT_RE = re.compile(
    r"^(?P<name>[^\n<>:\"/\\|?*]{1,200}\.\w{2,5}) "
    r"\((?:arquivo anexado|file attached|archivo adjunto)\)$",
    re.IGNORECASE,
)
_IOS_ATTACHMENT_RE = re.compile(
    r"<(?:anexado|attached|adjunto):\s*(?P<name>[^<>\n]{1,200})>", re.IGNORECASE
)

_OMITTED: tuple[tuple[re.Pattern[str], MessageKind], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), kind)
    for pattern, kind in (
        (r"^<(?:m[ií]dia oculta|arquivo de m[ií]dia oculto|media omitted|multimedia omitido)>$",
         MessageKind.OUTRO),
        (r"^(?:[aá]udio ocultad[oa]|[aá]udio omitid[oa]|audio omitted|audio omitido)$",
         MessageKind.AUDIO),
        (r"^(?:imagem ocultada|imagem omitida|image omitted|imagen omitida)$", MessageKind.IMAGEM),
        (r"^(?:v[ií]deo omitido|v[ií]deo ocultado|video omitted|video omitido)$", MessageKind.VIDEO),
        (r"^(?:figurinha omitida|sticker omitted|sticker omitido)$", MessageKind.FIGURINHA),
        (r"^gif (?:omitido|omitted)$", MessageKind.IMAGEM),
        (r"^(?:documento omitido|document omitted)$", MessageKind.DOCUMENTO),
        (r"^(?:cart[aã]o de contato omitido|contact card omitted|tarjeta de contacto omitida)$",
         MessageKind.CONTATO),
    )
)  # fmt: skip

_DELETED_RE = re.compile(
    r"^(?:mensagem apagada|(?:essa|esta) mensagem foi apagada|voc[eê] apagou (?:essa|esta) mensagem"
    r"|this message was deleted|you deleted this message"
    r"|se elimin[oó] este mensaje|eliminaste este mensaje)\.?$",
    re.IGNORECASE,
)
_EDITED_RE = re.compile(
    r"\s*<(?:mensagem editada|this message was edited|se edit[oó] este mensaje)>\s*$",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r"^(?:localiza[cç][aã]o|location|ubicaci[oó]n):\s*https?://\S+$"
    r"|^(?:localiza[cç][aã]o em tempo real compartilhada|live location shared)$",
    re.IGNORECASE,
)

#: Avisos do próprio WhatsApp. Ancorados no início: uma mensagem de verdade que só *contém* uma
#: destas expressões não pode ser descartada como "sistema".
_SYSTEM_RE = re.compile(
    r"^(?:"
    r"as mensagens e (?:as )?(?:liga[cç][oõ]es|chamadas) s[aã]o protegidas"
    r"|messages and calls are end-to-end encrypted"
    r"|los mensajes y las llamadas est[aá]n cifrados"
    r"|(?:liga[cç][aã]o|chamada) de (?:voz|v[ií]deo) perdida"
    r"|missed (?:voice|video) call"
    r"|(?:o|seu) c[oó]digo de seguran[cç]a"
    r"|your security code"
    r"|voc[eê] (?:bloqueou|desbloqueou) (?:este|esse) contato"
    r"|you (?:blocked|unblocked) this contact"
    r"|esta (?:empresa|conta comercial)"
    r"|this business"
    r"|(?:as )?mensagens tempor[aá]rias"
    r"|disappearing messages"
    r"|[^:\n]{1,80} (?:ativou|desativou|definiu) (?:as mensagens tempor[aá]rias|a dura[cç][aã]o)"
    r"|[^:\n]{1,80} (?:criou|created) (?:o |este |this )?(?:grupo|group)"
    r"|[^:\n]{1,80} (?:adicionou|removeu|added|removed) .{1,120}$"
    r"|[^:\n]{1,80} (?:saiu|left)$"
    r"|[^:\n]{1,80} (?:entrou usando|joined using)"
    r"|[^:\n]{1,80} (?:mudou|changed) (?:o |a |the |this |to )"
    r"|[^:\n]{1,80} (?:agora [eé] admin|is now an admin)"
    r"|[^:\n]{1,80} fixou uma mensagem|[^:\n]{1,80} pinned a message"
    r")",
    re.IGNORECASE,
)


class ParseError(ValueError):
    """O texto não parece um export de conversa do WhatsApp."""


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    index: int
    #: Horário local do aparelho que exportou, sem fuso.
    timestamp: datetime
    #: ``None`` em avisos do próprio WhatsApp.
    author: str | None
    #: Texto da mensagem (legenda, no caso de anexo). Vazio para mídia sem legenda.
    text: str
    kind: MessageKind = MessageKind.TEXTO
    #: Nome do arquivo anexado, quando o export foi feito "com mídia".
    attachment: str | None = None
    edited: bool = False


@dataclass(slots=True)
class ParsedChat:
    messages: list[ParsedMessage]
    platform: Platform
    date_order: DateOrder
    #: Verdadeiro quando o arquivo não permitiu decidir entre dia/mês e mês/dia.
    date_order_ambiguous: bool = False
    warnings: list[str] = field(default_factory=list)
    #: Mensagens descartadas por excederem ``max_messages`` (as mais antigas).
    truncated: int = 0

    @property
    def authors(self) -> list[str]:
        """Autores na ordem em que aparecem (sem os avisos de sistema)."""
        seen: dict[str, None] = {}
        for message in self.messages:
            if message.author is not None and message.kind is not MessageKind.SISTEMA:
                seen.setdefault(message.author)
        return list(seen)

    @property
    def content_messages(self) -> list[ParsedMessage]:
        """Mensagens de pessoas (sem avisos de sistema)."""
        return [m for m in self.messages if m.kind is not MessageKind.SISTEMA]


@dataclass(slots=True)
class _Entry:
    d1: str
    d2: str
    d3: str
    hour: int
    minute: int
    second: int
    ampm: str | None
    lines: list[str]


def strip_marks(text: str) -> str:
    """Remove marcas invisíveis de direção e BOM."""
    return _MARKS_RE.sub("", text)


def _match_header(line: str) -> re.Match[str] | None:
    match = _HEADER_RE.match(line)
    if match is None:
        return None
    hour, minute = int(match["h"]), int(match["mi"])
    if minute > 59 or hour > 23 or (match["ampm"] and not 1 <= hour <= 12):
        return None
    if match["s"] and int(match["s"]) > 59:
        return None
    return match


def _scan(text: str) -> tuple[list[_Entry], Platform]:
    entries: list[_Entry] = []
    platform: Platform | None = None
    for raw_line in text.split("\n"):
        line = raw_line.rstrip("\r")
        match = _match_header(line)
        if match is not None:
            line_platform: Platform = "ios" if match["bracket"] else "android"
            if platform is None:
                platform = line_platform
            if line_platform == platform:
                entries.append(
                    _Entry(
                        d1=match["d1"],
                        d2=match["d2"],
                        d3=match["d3"],
                        hour=int(match["h"]),
                        minute=int(match["mi"]),
                        second=int(match["s"] or 0),
                        ampm=match["ampm"].lower() if match["ampm"] else None,
                        lines=[match["rest"] or ""],
                    )
                )
                continue
        if entries:
            entries[-1].lines.append(line)
    if not entries or platform is None:
        raise ParseError(
            "Não reconheci este arquivo como um export de conversa do WhatsApp. "
            'No aplicativo, abra a conversa e use "Mais" → "Exportar conversa".'
        )
    return entries, platform


def _year(value: str) -> int:
    year = int(value)
    return year + 2000 if len(value) <= 2 else year


def _to_date(entry: _Entry, order: DateOrder) -> tuple[int, int, int] | None:
    try:
        if order == "ymd":
            year, month, day = int(entry.d1), int(entry.d2), int(entry.d3)
        elif order == "dmy":
            day, month, year = int(entry.d1), int(entry.d2), _year(entry.d3)
        else:
            month, day, year = int(entry.d1), int(entry.d2), _year(entry.d3)
        datetime(year, month, day)  # só valida a data
    except ValueError:
        return None
    return year, month, day


def _score_order(entries: list[_Entry], order: DateOrder) -> tuple[int, int, int]:
    """(datas inválidas, inversões de ordem, amplitude em dias): quanto menor, mais plausível."""
    dates = [_to_date(entry, order) for entry in entries]
    valid = [d for d in dates if d is not None]
    invalid = len(dates) - len(valid)
    inversions = sum(1 for prev, cur in itertools.pairwise(valid) if cur < prev)
    span = 0
    if valid:
        first, last = min(valid), max(valid)
        span = (datetime(*last) - datetime(*first)).days
    return invalid, inversions, span


def infer_date_order(entries: list[_Entry]) -> tuple[DateOrder, bool]:
    """Decide a ordem de dia e mês olhando todas as datas do arquivo."""
    if any(len(entry.d1) == 4 for entry in entries):
        return "ymd", False
    dmy, mdy = _score_order(entries, "dmy"), _score_order(entries, "mdy")
    if dmy != mdy:
        return ("dmy", False) if dmy < mdy else ("mdy", False)
    # Empate total: todas as datas valem nas duas leituras e contam a mesma história.
    uses_ampm = any(entry.ampm for entry in entries)
    same_reading = all(entry.d1 == entry.d2 for entry in entries)
    return ("mdy" if uses_ampm else "dmy"), not same_reading


def _split_author(rest: str) -> tuple[str | None, str]:
    clean = rest.lstrip(_MARKS + " ")
    if _SYSTEM_RE.match(strip_marks(clean)):
        return None, clean
    index = clean.find(": ")
    if index == -1:
        if clean.endswith(":") and 0 < len(clean) - 1 <= _MAX_AUTHOR_LENGTH:
            return _clean_author(clean[:-1]), ""
        return None, clean
    candidate = clean[:index]
    if len(candidate) > _MAX_AUTHOR_LENGTH or not candidate.strip():
        return None, clean
    return _clean_author(candidate), clean[index + 2 :]


def _clean_author(author: str) -> str:
    # Em grupos, contatos não salvos aparecem como "~ Nome" (com espaço estreito no iOS).
    return re.sub(r"\s+", " ", strip_marks(author).lstrip("~").replace(" ", " ")).strip()


def kind_from_filename(name: str) -> MessageKind:
    stem, _, ext = name.rpartition(".")
    ext = ext.lower()
    if ext in _AUDIO_EXT:
        return MessageKind.AUDIO
    if ext in _STICKER_EXT or stem.upper().startswith("STK-") or "-STICKER-" in stem.upper():
        return MessageKind.FIGURINHA
    if ext in _IMAGE_EXT:
        return MessageKind.IMAGEM
    if ext in _VIDEO_EXT:
        return MessageKind.VIDEO
    if ext in _CONTACT_EXT:
        return MessageKind.CONTATO
    return MessageKind.DOCUMENTO


def _classify(body: str) -> tuple[MessageKind, str, str | None, bool]:
    """Devolve ``(tipo, texto, anexo, editada)`` para o corpo de uma mensagem com autor."""
    had_mark = body.startswith("‎")
    text = strip_marks(body).strip()

    edited = False
    edited_match = _EDITED_RE.search(text)
    if edited_match:
        text, edited = text[: edited_match.start()].rstrip(), True

    first_line, _, remainder = text.partition("\n")

    android = _ANDROID_ATTACHMENT_RE.match(first_line.strip())
    if android:
        name = android["name"].strip()
        return kind_from_filename(name), remainder.strip(), name, edited

    ios = _IOS_ATTACHMENT_RE.search(text)
    if ios:
        name = ios["name"].strip()
        caption = (text[: ios.start()] + text[ios.end() :]).strip()
        return kind_from_filename(name), caption, name, edited

    for pattern, kind in _OMITTED:
        if pattern.match(first_line.strip()):
            return kind, remainder.strip(), None, edited

    if _DELETED_RE.match(text):
        return MessageKind.APAGADA, "", None, edited
    if text == "null":
        # Mídia de visualização única: o Android exporta literalmente "null".
        return MessageKind.OUTRO, "", None, edited
    if _LOCATION_RE.match(text):
        return MessageKind.LOCALIZACAO, "", None, edited
    # No iOS os avisos do sistema vêm atribuídos a um participante e marcados com U+200E.
    if had_mark and _SYSTEM_RE.match(text):
        return MessageKind.SISTEMA, text, None, edited
    return MessageKind.TEXTO, text, None, edited


def _to_datetime(entry: _Entry, order: DateOrder) -> datetime | None:
    date = _to_date(entry, order)
    if date is None:
        return None
    hour = entry.hour
    if entry.ampm == "p" and hour != 12:
        hour += 12
    elif entry.ampm == "a" and hour == 12:
        hour = 0
    return datetime(*date, hour, entry.minute, entry.second)


def parse_chat(text: str, *, max_messages: int | None = None) -> ParsedChat:
    """Lê o texto de um export do WhatsApp.

    Levanta :class:`ParseError` se nenhuma linha tiver o formato de mensagem. Com
    ``max_messages``, conversas maiores ficam só com as mensagens mais recentes (e um aviso).
    """
    entries, platform = _scan(text)
    order, ambiguous = infer_date_order(entries)
    warnings: list[str] = []
    if ambiguous:
        warnings.append(
            "As datas deste arquivo valem tanto como dia/mês quanto como mês/dia. "
            f"Assumi {'mês/dia' if order == 'mdy' else 'dia/mês'}; confira as datas da conversa."
        )

    messages: list[ParsedMessage] = []
    invalid_dates = 0
    for entry in entries:
        timestamp = _to_datetime(entry, order)
        body = "\n".join(entry.lines)
        if timestamp is None:
            # Parecia um cabeçalho, mas a data não existe: é continuação da mensagem anterior.
            invalid_dates += 1
            if messages:
                last = messages[-1]
                rebuilt = f"{last.text}\n{body}".strip()
                messages[-1] = ParsedMessage(
                    last.index,
                    last.timestamp,
                    last.author,
                    rebuilt,
                    last.kind,
                    last.attachment,
                    last.edited,
                )
            continue
        author, content = _split_author(body)
        if author is None:
            kind, text_value, attachment, edited = (
                MessageKind.SISTEMA,
                strip_marks(content),
                None,
                False,
            )
        else:
            kind, text_value, attachment, edited = _classify(content)
        messages.append(
            ParsedMessage(
                index=len(messages),
                timestamp=timestamp,
                author=author,
                text=text_value.strip(),
                kind=kind,
                attachment=attachment,
                edited=edited,
            )
        )

    if invalid_dates:
        warnings.append(
            f"{invalid_dates} linha(s) pareciam mensagens, mas tinham data inválida e foram "
            "tratadas como continuação da mensagem anterior."
        )
    if not any(m.author is not None for m in messages):
        raise ParseError(
            "O arquivo tem o formato do WhatsApp, mas nenhuma mensagem de participante."
        )

    truncated = 0
    if max_messages is not None and len(messages) > max_messages:
        truncated = len(messages) - max_messages
        kept = messages[-max_messages:]
        messages = [
            ParsedMessage(i, m.timestamp, m.author, m.text, m.kind, m.attachment, m.edited)
            for i, m in enumerate(kept)
        ]
        warnings.append(
            f"A conversa tem mais de {max_messages} mensagens; as {truncated} mais antigas "
            "foram ignoradas."
        )

    return ParsedChat(
        messages=messages,
        platform=platform,
        date_order=order,
        date_order_ambiguous=ambiguous,
        warnings=warnings,
        truncated=truncated,
    )


_TITLE_RE = re.compile(
    r"^(?:conversa do whatsapp com|whatsapp chat with|chat de whatsapp con"
    r"|conversa do whatsapp -|whatsapp chat -)\s*(?P<title>.+?)(?:\s*\(\d+\))?(?:\.(?:txt|zip))?$",
    re.IGNORECASE,
)


def chat_title_from_filename(filename: str) -> str | None:
    """Extrai o nome da outra pessoa (ou do grupo) do nome padrão do arquivo exportado."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    match = _TITLE_RE.match(strip_marks(base))
    if match is None:
        return None
    return match["title"].strip() or None
