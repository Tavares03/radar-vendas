"""Ingestão: transforma um export, uma chamada de API ou um webhook em conversa e mensagens.

Tudo passa por :func:`ingest_conversation`, que é idempotente: reenviar o mesmo conteúdo não
duplica nada, e reenviar um export mais novo da mesma conversa só acrescenta o que falta.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.config import Settings, get_settings
from radar.db.models import Conversation, Import, Message, Seller, Tenant
from radar.db.session import session_scope
from radar.ingest import (
    ArchiveLimits,
    ExportBundle,
    InvalidExport,
    ParsedChat,
    ParseError,
    ParticipantInfo,
    SellerRef,
    UnsafeArchive,
    identify_participants,
    open_export,
    parse_chat,
)
from radar.logs import get_logger
from radar.privacy.crypto import encrypt_text, pseudonym, subject_hash
from radar.taxonomy import (
    ConversationStatus,
    ImportSource,
    ImportStatus,
    MessageKind,
    SenderRole,
    TranscriptionStatus,
)

log = get_logger(__name__)

_MB = 1024 * 1024
_CHUNK = 1024 * 1024
_SAFE_EXT_RE = re.compile(r"^[a-z0-9]{1,5}$")

#: Erros que são culpa do arquivo, não do sistema: a mensagem vai para o usuário como está.
USER_ERRORS = (ParseError, InvalidExport, UnsafeArchive)


class UploadTooLarge(ValueError):
    """O arquivo enviado passa do limite configurado."""


@dataclass(slots=True)
class IncomingMessage:
    """Uma mensagem a caminho do banco, já com horário com fuso."""

    sent_at: datetime
    author: str
    text: str = ""
    kind: MessageKind = MessageKind.TEXTO
    media_name: str | None = None
    edited: bool = False
    #: Transcrição que já veio pronta (áudio sintético, webhook que já transcreve…).
    transcript: str | None = None
    #: Id da mensagem no sistema de origem; quando existe, é ele que evita duplicatas.
    external_id: str | None = None


@dataclass(slots=True)
class IngestResult:
    conversation: Conversation
    created: bool
    new_messages: list[Message] = field(default_factory=list)
    duplicates: int = 0
    #: Hash de deduplicação → mensagem de entrada (para ligar anexos às linhas criadas).
    by_hash: dict[str, IncomingMessage] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoredUpload:
    path: Path
    sha256: str
    size: int


# ---------------------------------------------------------------- utilidades
def tenant_timezone(tenant: Tenant) -> ZoneInfo:
    name = tenant.get_settings().timezone
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("fuso_invalido", timezone=name)
        return ZoneInfo("America/Sao_Paulo")


def to_utc(value: datetime, zone: ZoneInfo) -> datetime:
    """Aplica o fuso da empresa a um horário sem fuso e converte para UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    return value.astimezone(UTC)


def archive_limits(settings: Settings) -> ArchiveLimits:
    return ArchiveLimits(
        max_files=settings.max_zip_files,
        max_uncompressed_bytes=settings.max_zip_uncompressed_mb * _MB,
        max_ratio=settings.max_zip_ratio,
    )


def relative_to_data(path: Path, settings: Settings) -> str:
    return path.resolve().relative_to(settings.data_dir.resolve()).as_posix()


def data_path(relative: str, settings: Settings) -> Path:
    """Caminho absoluto de um arquivo guardado, recusando qualquer fuga de ``data_dir``."""
    base = settings.data_dir.resolve()
    full = (base / relative).resolve()
    if not full.is_relative_to(base):
        raise ValueError("caminho fora da pasta de dados")
    return full


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:2000]


def _dedupe_hashes(
    messages: Sequence[IncomingMessage], author_keys: Mapping[str, str]
) -> list[str]:
    seen: dict[str, int] = {}
    hashes: list[str] = []
    for message in messages:
        if message.external_id:
            base = f"ext|{message.external_id}"
        else:
            stamp = message.sent_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
            base = "|".join(
                (
                    stamp,
                    author_keys[message.author],
                    message.kind.value,
                    _normalize_text(message.text),
                    message.media_name or "",
                )
            )
        # Duas mensagens idênticas no mesmo instante ("ok", "ok") são distintas pela ordem.
        occurrence = seen.get(base, 0)
        seen[base] = occurrence + 1
        hashes.append(hashlib.sha256(f"{base}#{occurrence}".encode()).hexdigest())
    return hashes


def seller_refs(db: Session) -> list[SellerRef]:
    sellers = db.scalars(select(Seller).where(Seller.is_active.is_(True))).all()
    return [SellerRef(s.id, s.display_name, tuple(s.aliases or ())) for s in sellers]


def _get_or_create_seller(db: Session, tenant_id: uuid.UUID, name: str) -> Seller:
    display = name.strip()[:200] or "Vendedor"
    existing = db.scalar(select(Seller).where(Seller.display_name == display))
    if existing is not None:
        return existing
    seller = Seller(tenant_id=tenant_id, display_name=display, aliases=[])
    db.add(seller)
    db.flush()
    log.info("vendedor_criado_na_importacao", seller_id=str(seller.id))
    return seller


# ---------------------------------------------------------------- núcleo
def ingest_conversation(
    db: Session,
    *,
    tenant: Tenant,
    source: ImportSource,
    participants: Mapping[str, ParticipantInfo],
    messages: Sequence[IncomingMessage],
    playbook: str | None = None,
    external_id: str | None = None,
    warnings: Sequence[str] = (),
) -> IngestResult:
    """Cria a conversa ou acrescenta as mensagens novas a uma conversa já existente.

    A sessão precisa estar no escopo da empresa. Quem chama faz o commit.
    """
    if not messages:
        raise ValueError("conversa sem mensagens")
    tenant_id = tenant.id
    author_keys = {author: subject_hash(tenant_id, author) for author in participants}
    missing = {m.author for m in messages} - set(author_keys)
    if missing:
        raise ValueError("mensagem de autor sem papel definido")

    hashes = _dedupe_hashes(messages, author_keys)
    by_hash = dict(zip(hashes, messages, strict=True))
    fingerprint = hashlib.sha256(
        "|".join([source.value, *sorted(author_keys.values())]).encode()
    ).hexdigest()

    # ---- conversa existente?
    conversation: Conversation | None = None
    existing_hashes: set[str] = set()
    if external_id:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.source == source, Conversation.external_id == external_id
            )
        )
        if conversation is not None:
            existing_hashes = set(
                db.scalars(
                    select(Message.dedupe_hash).where(Message.conversation_id == conversation.id)
                )
            )
    else:
        candidates = db.scalars(
            select(Conversation)
            .where(Conversation.source == source, Conversation.fingerprint == fingerprint)
            .order_by(Conversation.created_at)
        ).all()
        incoming = set(hashes)
        for candidate in candidates:
            candidate_hashes = set(
                db.scalars(
                    select(Message.dedupe_hash).where(Message.conversation_id == candidate.id)
                )
            )
            # Mesmos participantes não bastam (dois clientes "Maria"): precisa haver mensagem
            # em comum para ser a mesma conversa.
            if candidate_hashes & incoming:
                conversation, existing_hashes = candidate, candidate_hashes
                break

    created = conversation is None
    if conversation is None:
        conversation = _new_conversation(
            db,
            tenant=tenant,
            source=source,
            participants=participants,
            author_keys=author_keys,
            messages=messages,
            fingerprint=fingerprint,
            external_id=external_id,
            playbook=playbook,
        )

    # ---- mensagens novas
    max_position = db.scalar(
        select(func.max(Message.position)).where(Message.conversation_id == conversation.id)
    )
    next_position = 0 if max_position is None else max_position + 1

    new_rows: list[Message] = []
    for digest, message in by_hash.items():
        if digest in existing_hashes:
            continue
        info = participants[message.author]
        is_audio = message.kind is MessageKind.AUDIO
        text = message.transcript if is_audio and message.transcript else message.text
        if is_audio:
            status = (
                TranscriptionStatus.CONCLUIDA
                if message.transcript
                else TranscriptionStatus.IGNORADA
            )
        else:
            status = TranscriptionStatus.NAO_APLICAVEL
        row = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            position=next_position + len(new_rows),
            sent_at=message.sent_at,
            sender_role=info.role,
            sender_key=author_keys[message.author],
            kind=message.kind,
            text_raw=text,
            dedupe_hash=digest,
            media_name=message.media_name,
            transcription_status=status,
            transcription_model="origem" if is_audio and message.transcript else "",
            edited=message.edited,
        )
        db.add(row)
        new_rows.append(row)
    db.flush()

    if new_rows or created:
        _refresh_counters(db, conversation)
        conversation.status = ConversationStatus.PENDENTE
        merged = list(dict.fromkeys([*(conversation.warnings or []), *warnings]))
        conversation.warnings = merged[:20]

    return IngestResult(
        conversation=conversation,
        created=created,
        new_messages=new_rows,
        duplicates=len(by_hash) - len(new_rows),
        by_hash=by_hash,
    )


def _new_conversation(
    db: Session,
    *,
    tenant: Tenant,
    source: ImportSource,
    participants: Mapping[str, ParticipantInfo],
    author_keys: Mapping[str, str],
    messages: Sequence[IncomingMessage],
    fingerprint: str,
    external_id: str | None,
    playbook: str | None,
) -> Conversation:
    counts: dict[str, int] = {}
    for message in messages:
        counts[message.author] = counts.get(message.author, 0) + 1

    def busiest(role: SenderRole) -> str | None:
        authors = [a for a, info in participants.items() if info.role is role]
        return max(authors, key=lambda a: counts.get(a, 0)) if authors else None

    seller_author = busiest(SenderRole.VENDEDOR)
    customer_author = busiest(SenderRole.CLIENTE)

    seller: Seller | None = None
    seller_by_author: dict[str, Seller] = {}
    for author, info in participants.items():
        if info.role is not SenderRole.VENDEDOR:
            continue
        found = db.get(Seller, info.seller_id) if info.seller_id else None
        seller_by_author[author] = found or _get_or_create_seller(db, tenant.id, author)
    if seller_author is not None:
        seller = seller_by_author[seller_author]

    entries = []
    for author, info in participants.items():
        if info.role is SenderRole.VENDEDOR:
            label = seller_by_author[author].display_name
            seller_id: str | None = str(seller_by_author[author].id)
        else:
            label, seller_id = pseudonym(tenant.id, author), None
        entries.append(
            {
                "key": author_keys[author],
                "role": info.role.value,
                "seller_id": seller_id,
                "label": label,
                "name_enc": encrypt_text(author),
                "confidence": info.confidence,
                "reason": info.reason,
            }
        )

    confidences = {info.confidence for info in participants.values()}
    confidence = (
        "baixa" if "baixa" in confidences else "media" if "media" in confidences else "alta"
    )

    conversation = Conversation(
        tenant_id=tenant.id,
        seller_id=seller.id if seller else None,
        source=source,
        external_id=external_id,
        fingerprint=fingerprint,
        customer_label=pseudonym(tenant.id, customer_author) if customer_author else "Cliente",
        customer_name=customer_author,
        customer_hash=subject_hash(tenant.id, customer_author) if customer_author else None,
        playbook=playbook or tenant.default_playbook,
        status=ConversationStatus.PENDENTE,
        participants=entries,
        role_confidence=confidence,
        warnings=[],
    )
    db.add(conversation)
    db.flush()
    return conversation


def _refresh_counters(db: Session, conversation: Conversation) -> None:
    rows = db.execute(
        select(
            Message.sender_role,
            Message.kind,
            func.count(Message.id),
            func.min(Message.sent_at),
            func.max(Message.sent_at),
        )
        .where(Message.conversation_id == conversation.id)
        .group_by(Message.sender_role, Message.kind)
    ).all()
    total = seller = customer = audio = 0
    first: datetime | None = None
    last: datetime | None = None
    for role, kind, count, min_at, max_at in rows:
        total += count
        if SenderRole(role) is SenderRole.VENDEDOR:
            seller += count
        elif SenderRole(role) is SenderRole.CLIENTE:
            customer += count
        if MessageKind(kind) is MessageKind.AUDIO:
            audio += count
        oldest, newest = _aware(min_at), _aware(max_at)
        if oldest is not None and (first is None or oldest < first):
            first = oldest
        if newest is not None and (last is None or newest > last):
            last = newest
    conversation.message_count = total
    conversation.seller_message_count = seller
    conversation.customer_message_count = customer
    conversation.audio_count = audio
    conversation.started_at = first
    conversation.last_message_at = last


def _aware(value: datetime | str | None) -> datetime | None:
    # Agregações (min/max) não passam pelo TypeDecorator: o SQLite devolve texto sem fuso.
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# ---------------------------------------------------------------- uploads
def store_upload(source: BinaryIO, *, tenant_id: uuid.UUID, settings: Settings) -> StoredUpload:
    """Grava o upload em disco com um nome interno, calculando hash e tamanho no caminho."""
    limit = settings.max_upload_mb * _MB
    folder = settings.uploads_dir / str(tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{uuid.uuid4().hex}.upload"
    digest = hashlib.sha256()
    size = 0
    try:
        with destination.open("wb") as target:
            while chunk := source.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise UploadTooLarge(
                        f"O arquivo passa do limite de {settings.max_upload_mb} MB."
                    )
                digest.update(chunk)
                target.write(chunk)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return StoredUpload(destination, digest.hexdigest(), size)


def validate_export(path: Path, *, original_name: str, settings: Settings) -> ParsedChat:
    """Abre e lê o export; levanta um dos :data:`USER_ERRORS` se o arquivo não servir."""
    with open_export(path, original_name=original_name, limits=archive_limits(settings)) as bundle:
        return parse_chat(bundle.chat_text, max_messages=settings.max_messages_per_conversation)


def find_duplicate_import(db: Session, sha256: str) -> Import | None:
    """Importação concluída do mesmo arquivo, cuja conversa ainda existe."""
    return db.scalar(
        select(Import)
        .where(
            Import.file_sha256 == sha256,
            Import.status == ImportStatus.CONCLUIDO,
            Import.conversation_id.is_not(None),
        )
        .order_by(Import.created_at.desc())
    )


# ---------------------------------------------------------------- processamento do export
def _incoming_from_chat(chat: ParsedChat, zone: ZoneInfo) -> list[IncomingMessage]:
    return [
        IncomingMessage(
            sent_at=to_utc(message.timestamp, zone),
            author=message.author or "",
            text=message.text,
            kind=message.kind,
            media_name=message.attachment,
            edited=message.edited,
        )
        for message in chat.content_messages
        if message.author
    ]


def _attach_audio(
    db: Session,
    bundle: ExportBundle,
    result: IngestResult,
    settings: Settings,
) -> tuple[int, int]:
    """Guarda os áudios das mensagens novas. Devolve ``(para transcrever, sem arquivo)``."""
    pending = missing = 0
    by_row_hash = {row.dedupe_hash: row for row in result.new_messages}
    for digest, row in by_row_hash.items():
        if row.kind is not MessageKind.AUDIO:
            continue
        name = result.by_hash[digest].media_name
        if not name or not bundle.has_media(name):
            row.transcription_status = TranscriptionStatus.IGNORADA
            missing += 1
            continue
        sidecar = bundle.read_sidecar(name)
        if sidecar:
            row.text_raw = sidecar
            row.transcription_status = TranscriptionStatus.CONCLUIDA
            row.transcription_model = "origem"
            continue
        ext = name.rsplit(".", 1)[-1].lower()
        if not _SAFE_EXT_RE.match(ext):
            ext = "bin"
        destination = (
            settings.media_dir
            / str(row.tenant_id)
            / str(row.conversation_id)
            / f"{uuid.uuid4().hex}.{ext}"
        )
        try:
            bundle.save_media(name, destination)
        except UnsafeArchive:
            row.transcription_status = TranscriptionStatus.IGNORADA
            missing += 1
            continue
        row.media_path = relative_to_data(destination, settings)
        row.transcription_status = TranscriptionStatus.PENDENTE
        pending += 1
    db.flush()
    return pending, missing


def import_export(db: Session, record: Import, tenant: Tenant, settings: Settings) -> IngestResult:
    """Lê o arquivo de uma importação e grava conversa, mensagens e áudios."""
    if not record.stored_path:
        raise InvalidExport("O arquivo desta importação não está mais disponível.")
    path = data_path(record.stored_path, settings)
    options = record.options or {}

    with open_export(
        path, original_name=record.filename, limits=archive_limits(settings)
    ) as bundle:
        chat = parse_chat(bundle.chat_text, max_messages=settings.max_messages_per_conversation)
        refs = seller_refs(db)
        forced: SellerRef | None = None
        if options.get("seller_id"):
            forced = next((r for r in refs if str(r.id) == options["seller_id"]), None)
        participants = identify_participants(
            chat.authors,
            sellers=refs,
            seller_hint=options.get("seller_name") or None,
            forced_seller=forced,
            chat_title=bundle.title,
            messages=chat.content_messages,
        )
        result = ingest_conversation(
            db,
            tenant=tenant,
            source=record.source,
            participants=participants,
            messages=_incoming_from_chat(chat, tenant_timezone(tenant)),
            playbook=options.get("playbook") or None,
            warnings=chat.warnings,
        )
        pending_audio, missing_audio = _attach_audio(db, bundle, result, settings)

    if missing_audio:
        note = (
            "1 áudio veio sem o arquivo e não foi transcrito. "
            if missing_audio == 1
            else f"{missing_audio} áudios vieram sem o arquivo e não foram transcritos. "
        ) + 'Para incluí-los, exporte a conversa com a opção "Incluir mídia".'
        result.conversation.warnings = list(
            dict.fromkeys([*(result.conversation.warnings or []), note])
        )
    record.stats = {
        "mensagens_novas": len(result.new_messages),
        "mensagens_repetidas": result.duplicates,
        "mensagens_de_sistema": len(chat.messages) - len(chat.content_messages),
        "audios_para_transcrever": pending_audio,
        "audios_sem_arquivo": missing_audio,
        "conversa_nova": result.created,
        "formato": chat.platform,
        "ordem_da_data": chat.date_order,
        "avisos": chat.warnings,
    }
    record.conversation_id = result.conversation.id
    return result


def process_import(import_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Job: processa um arquivo enviado e dispara a análise da conversa."""
    from radar.worker.jobs import enqueue_conversation

    settings = get_settings()
    conversation_id: uuid.UUID | None = None
    has_news = False
    with session_scope(tenant_id) as db:
        record = db.get(Import, import_id)
        tenant = db.get(Tenant, tenant_id)
        if record is None or tenant is None:
            log.warning("importacao_nao_encontrada", import_id=str(import_id))
            return
        if record.status is ImportStatus.CONCLUIDO:
            return
        record.status = ImportStatus.PROCESSANDO
        record.error = ""
        db.commit()
        stored_path = record.stored_path
        try:
            result = import_export(db, record, tenant, settings)
            record.status = ImportStatus.CONCLUIDO
            conversation_id = result.conversation.id
            has_news = bool(result.new_messages) or result.created
        except USER_ERRORS as exc:
            db.rollback()
            record.status = ImportStatus.FALHOU
            record.error = str(exc)
        except Exception:
            db.rollback()
            log.exception("importacao_falhou", import_id=str(import_id))
            record.status = ImportStatus.FALHOU
            record.error = "Erro interno ao processar o arquivo. O incidente foi registrado."
        finally:
            # Minimização: o upload só existe em disco enquanto é processado.
            if stored_path:
                try:
                    data_path(stored_path, settings).unlink(missing_ok=True)
                except (OSError, ValueError):
                    log.warning("upload_nao_removido", import_id=str(import_id))
            record.stored_path = None
            record.finished_at = datetime.now(UTC)
            db.commit()

    if conversation_id is not None and has_news:
        enqueue_conversation(conversation_id, tenant_id)
