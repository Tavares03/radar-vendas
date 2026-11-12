"""Abertura segura de um export do WhatsApp (``.txt`` solto ou ``.zip`` com mídia).

Um upload é entrada hostil até prova em contrário. Antes de ler qualquer conteúdo do zip:

- quantidade de arquivos e tamanho total descompactado têm teto;
- a taxa de compressão de cada arquivo tem teto (zip bomb);
- nomes com ``..``, caminhos absolutos, letras de unidade e links simbólicos são recusados;
- arquivos cifrados são recusados; zips dentro do zip são ignorados.

Nada é extraído para o disco com o nome que veio no zip: o texto é lido em memória e cada áudio é
gravado, sob demanda, num caminho escolhido por quem chama. O tamanho declarado no cabeçalho não
é confiado: a leitura conta os bytes e para no limite.
"""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self

from radar.ingest.whatsapp import chat_title_from_filename, kind_from_filename
from radar.taxonomy import MessageKind

_MB = 1024 * 1024
_CHUNK = 64 * 1024
#: Abaixo deste tamanho a taxa de compressão não é verificada (texto pequeno comprime muito).
_RATIO_MIN_BYTES = 1 * _MB
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class UnsafeArchive(ValueError):
    """O arquivo enviado foi recusado por segurança."""


class InvalidExport(ValueError):
    """O arquivo não contém uma conversa exportada do WhatsApp."""


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_files: int = 5000
    max_uncompressed_bytes: int = 1024 * _MB
    max_ratio: int = 200
    max_chat_bytes: int = 64 * _MB
    max_media_bytes: int = 64 * _MB


def is_zip(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) in _ZIP_MAGIC


def decode_text(data: bytes) -> str:
    """Decodifica o ``.txt`` do export (UTF-8; UTF-16 com BOM em aparelhos antigos)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _check_name(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or "\x00" in normalized
        or (len(normalized) > 1 and normalized[1] == ":")
        or ".." in path.parts
    ):
        raise UnsafeArchive(f"Nome de arquivo inválido dentro do zip: {name[:80]!r}")
    return path


def _read_limited(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with archive.open(info) as source:
        while True:
            chunk = source.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise UnsafeArchive(
                    f"O arquivo {info.filename[:80]!r} é maior do que o limite permitido."
                )
            chunks.append(chunk)
    return b"".join(chunks)


class ExportBundle:
    """Um export aberto: o texto da conversa e acesso controlado às mídias."""

    def __init__(
        self,
        *,
        chat_text: str,
        chat_name: str,
        title: str | None,
        archive: zipfile.ZipFile | None,
        media: dict[str, zipfile.ZipInfo],
        limits: ArchiveLimits,
    ) -> None:
        self.chat_text = chat_text
        self.chat_name = chat_name
        self.title = title
        self._archive = archive
        self._media = media
        self._limits = limits

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._archive is not None:
            self._archive.close()
            self._archive = None

    @property
    def media_names(self) -> list[str]:
        return sorted(self._media)

    def has_media(self, name: str) -> bool:
        return name in self._media

    def audio_names(self) -> list[str]:
        return [n for n in self.media_names if kind_from_filename(n) is MessageKind.AUDIO]

    def read_media(self, name: str) -> bytes:
        """Conteúdo de um anexo, limitado a ``max_media_bytes``."""
        if self._archive is None or name not in self._media:
            raise KeyError(name)
        return _read_limited(self._archive, self._media[name], self._limits.max_media_bytes)

    def read_sidecar(self, name: str) -> str | None:
        """Transcrição que acompanha um áudio (``<áudio>.txt``), usada em demos e testes."""
        sidecar = f"{name}.txt"
        if self._archive is None or sidecar not in self._media:
            return None
        return decode_text(self.read_media(sidecar)).strip()

    def save_media(self, name: str, destination: Path) -> Path:
        """Grava um anexo em ``destination`` (caminho escolhido por quem chama)."""
        data = self.read_media(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination


def _validate_zip(archive: zipfile.ZipFile, limits: ArchiveLimits) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > limits.max_files:
        raise UnsafeArchive(
            f"O zip tem arquivos demais ({len(infos)}; o limite é {limits.max_files})."
        )
    total = 0
    files: list[zipfile.ZipInfo] = []
    for info in infos:
        _check_name(info.filename)
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise UnsafeArchive("O zip contém links simbólicos, o que não é permitido.")
        if info.flag_bits & 0x1:
            raise UnsafeArchive("O zip está protegido por senha. Exporte a conversa sem senha.")
        if info.is_dir():
            continue
        total += info.file_size
        if total > limits.max_uncompressed_bytes:
            raise UnsafeArchive("O conteúdo descompactado do zip excede o limite permitido.")
        if (
            info.file_size > _RATIO_MIN_BYTES
            and info.file_size > max(info.compress_size, 1) * limits.max_ratio
        ):
            raise UnsafeArchive(
                "O zip tem taxa de compressão anormal (possível zip bomb) e foi recusado."
            )
        files.append(info)
    return files


def _pick_chat_file(files: list[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    texts = [f for f in files if f.filename.lower().endswith(".txt")]
    if not texts:
        raise InvalidExport("O zip não contém o arquivo de texto da conversa (.txt).")

    def rank(info: zipfile.ZipInfo) -> tuple[int, int, int]:
        base = PurePosixPath(info.filename.replace("\\", "/")).name
        if base.lower() == "_chat.txt":
            named = 0
        elif chat_title_from_filename(base) is not None:
            named = 1
        else:
            named = 2
        depth = info.filename.replace("\\", "/").count("/")
        return named, depth, -info.file_size

    return min(texts, key=rank)


def open_export(
    path: Path, *, original_name: str | None = None, limits: ArchiveLimits | None = None
) -> ExportBundle:
    """Abre um ``.txt`` ou ``.zip`` exportado do WhatsApp, validando antes de ler.

    ``original_name`` é o nome do arquivo como o usuário enviou (o arquivo em disco costuma ter um
    nome interno); ele ajuda a descobrir com quem é a conversa.
    """
    limits = limits or ArchiveLimits()
    display_name = original_name or path.name

    if not is_zip(path):
        size = path.stat().st_size
        if size > limits.max_chat_bytes:
            raise UnsafeArchive("O arquivo de texto é maior do que o limite permitido.")
        data = path.read_bytes()
        if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise InvalidExport("O arquivo não é um texto nem um zip exportado do WhatsApp.")
        return ExportBundle(
            chat_text=decode_text(data),
            chat_name=display_name,
            title=chat_title_from_filename(display_name),
            archive=None,
            media={},
            limits=limits,
        )

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise InvalidExport("O arquivo zip está corrompido.") from exc

    try:
        files = _validate_zip(archive, limits)
        chat_info = _pick_chat_file(files)
        chat_bytes = _read_limited(archive, chat_info, limits.max_chat_bytes)
        chat_base = PurePosixPath(chat_info.filename.replace("\\", "/")).name
        title = chat_title_from_filename(chat_base) or chat_title_from_filename(display_name)
        media: dict[str, zipfile.ZipInfo] = {}
        for info in files:
            if info is chat_info or info.filename.lower().endswith(".zip"):
                continue
            # As mensagens citam o anexo só pelo nome, sem pasta.
            media.setdefault(PurePosixPath(info.filename.replace("\\", "/")).name, info)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        archive.close()
        raise InvalidExport("Não foi possível ler o zip enviado.") from exc
    except BaseException:
        archive.close()
        raise

    return ExportBundle(
        chat_text=decode_text(chat_bytes),
        chat_name=chat_base,
        title=title,
        archive=archive,
        media=media,
        limits=limits,
    )
