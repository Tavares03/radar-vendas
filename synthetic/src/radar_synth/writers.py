"""Escreve a conversa sintética no formato de "Exportar conversa" do WhatsApp.

Android e iOS, em português ou inglês, com ou sem mídia. Os áudios viram um arquivo ``.opus``
de mentira acompanhado da transcrição (``<áudio>.txt``), que o Radar usa no lugar do Whisper em
demos e testes. Sem mídia, aparecem como no aplicativo ("<Mídia oculta>", "áudio ocultado").
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

from radar_synth.model import SynthConversation, SynthMessage

#: Bytes de um "áudio" sintético: só o cabeçalho Ogg (a transcrição vai no arquivo ao lado).
FAKE_OPUS = b"OggS\x00\x02" + b"\x00" * 20

_SYSTEM_PT = (
    "As mensagens e as ligações são protegidas com a criptografia de ponta a ponta e ficam "
    "somente entre você e os participantes desta conversa. Nem mesmo o WhatsApp pode ler ou "
    "ouvi-las."
)
_SYSTEM_EN = (
    "Messages and calls are end-to-end encrypted. No one outside of this chat, not even "
    "WhatsApp, can read or listen to them."
)
_LRM = "‎"


@dataclass(slots=True)
class ExportFiles:
    chat_name: str
    chat_text: str
    #: Anexos do zip: áudios falsos e as transcrições (``<áudio>.txt``).
    media: dict[str, bytes] = field(default_factory=dict)


def _title(conversation: SynthConversation, language: str) -> str:
    if language == "en":
        return f"WhatsApp Chat with {conversation.customer_display}"
    return f"Conversa do WhatsApp com {conversation.customer_display}"


def _stamp(moment: datetime, platform: str, language: str) -> str:
    if language == "en":
        hour = moment.hour % 12 or 12
        ampm = "AM" if moment.hour < 12 else "PM"
        date = f"{moment.month}/{moment.day}/{moment.year % 100:02d}"
        if platform == "ios":
            return f"[{date}, {hour}:{moment.minute:02d}:{moment.second:02d} {ampm}]"
        return f"{date}, {hour}:{moment.minute:02d} {ampm} -"
    date = moment.strftime("%d/%m/%Y")
    if platform == "ios":
        return f"[{date}, {moment.strftime('%H:%M:%S')}]"
    return f"{date} {moment.strftime('%H:%M')} -"


def _audio_name(message: SynthMessage, platform: str, counter: int) -> str:
    moment = message.timestamp
    if platform == "ios":
        return f"{counter:08d}-AUDIO-{moment.strftime('%Y-%m-%d-%H-%M-%S')}.opus"
    return f"PTT-{moment.strftime('%Y%m%d')}-WA{counter:04d}.opus"


def _audio_body(name: str | None, platform: str, language: str) -> str:
    if name is None:  # export sem mídia
        if platform == "ios":
            return _LRM + ("audio omitted" if language == "en" else "áudio ocultado")
        return "<Media omitted>" if language == "en" else "<Mídia oculta>"
    if platform == "ios":
        return _LRM + (f"<attached: {name}>" if language == "en" else f"<anexado: {name}>")
    return f"{name} (file attached)" if language == "en" else f"{name} (arquivo anexado)"


def render_export(
    conversation: SynthConversation,
    *,
    platform: str = "android",
    language: str = "pt",
    with_media: bool = True,
) -> ExportFiles:
    if platform not in ("android", "ios") or language not in ("pt", "en"):
        raise ValueError("plataforma deve ser android|ios e idioma pt|en")
    lines: list[str] = []
    media: dict[str, bytes] = {}
    first = conversation.messages[0].timestamp
    system = _SYSTEM_EN if language == "en" else _SYSTEM_PT
    if platform == "ios":
        lines.append(
            f"{_stamp(first, platform, language)} {conversation.seller_display}: {_LRM}{system}"
        )
    else:
        lines.append(f"{_stamp(first, platform, language)} {system}")

    counter = 0
    for message in conversation.messages:
        if message.kind == "audio":
            counter += 1
            name = _audio_name(message, platform, counter) if with_media else None
            if name is not None:
                media[name] = FAKE_OPUS
                media[f"{name}.txt"] = message.text.encode("utf-8")
            body = _audio_body(name, platform, language)
        else:
            body = message.text
        lines.append(f"{_stamp(message.timestamp, platform, language)} {message.author}: {body}")

    chat_name = "_chat.txt" if platform == "ios" else f"{_title(conversation, language)}.txt"
    return ExportFiles(chat_name=chat_name, chat_text="\n".join(lines) + "\n", media=media)


def export_zip(
    conversation: SynthConversation,
    *,
    platform: str = "android",
    language: str = "pt",
    with_media: bool = True,
) -> tuple[str, bytes]:
    """``(nome do zip, conteúdo)`` como o aplicativo entrega ao exportar."""
    files = render_export(conversation, platform=platform, language=language, with_media=with_media)
    buffer = io.BytesIO()
    # A data dos arquivos no zip é a do export (não a do relógio): o mesmo export gera o mesmo zip.
    stamp = conversation.exported_at.timetuple()[:6]

    def entry(name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        return info

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry(files.chat_name), files.chat_text.encode("utf-8"))
        for name, content in sorted(files.media.items()):
            archive.writestr(entry(name), content)
    return f"{_title(conversation, language)}.zip", buffer.getvalue()
