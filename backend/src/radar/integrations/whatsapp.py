"""WhatsApp ao vivo: transforma os eventos da Evolution API em conversas do Radar.

Cada número conectado pertence a um vendedor. Toda mensagem de um contato vira (ou continua) a
conversa daquele vendedor com aquele contato; ``fromMe`` diz quem falou, então não há dúvida de
quem é o vendedor. A análise não roda a cada mensagem: a conversa fica ``aguardando`` e o
agendador manda analisar depois de uma pausa (:func:`enqueue_idle_conversations`).

Contra esconder conversa ruim:

- mensagem apagada "para todos" continua no Radar, marcada como apagada (e a conversa ganha um
  aviso quando quem apagou foi o vendedor);
- mensagem editada guarda o texto original e o novo;
- desconectar o número fica registrado e visível para a gestão.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from radar.config import Settings
from radar.db.base import utcnow
from radar.db.models import (
    Conversation,
    Message,
    Seller,
    Tenant,
    WhatsAppConnection,
    WhatsAppIgnoredContact,
)
from radar.db.session import session_scope
from radar.ingest import ParticipantInfo
from radar.integrations.evolution import EvolutionClient, EvolutionError
from radar.logs import get_logger
from radar.privacy.crypto import subject_hash
from radar.services.audit import AuditAction, record_audit
from radar.services.ingestion import (
    IncomingMessage,
    external_message_hash,
    ingest_conversation,
    relative_to_data,
)
from radar.taxonomy import (
    ConversationStatus,
    ImportSource,
    MessageKind,
    SenderRole,
    TranscriptionStatus,
    WhatsAppState,
)


def enqueue_prepare(conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    # Import tardio: o módulo de jobs importa o agendador, que não precisa vir junto do webhook.
    from radar.worker.jobs import enqueue_prepare as enqueue

    enqueue(conversation_id, tenant_id)


log = get_logger(__name__)

#: Grupos, status e canais nunca entram: só conversa de um vendedor com um contato.
_SKIPPED_SERVERS = ("g.us", "broadcast", "newsletter", "call")
#: Embrulhos que o WhatsApp põe em volta da mensagem de verdade.
_WRAPPERS = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
    "documentWithCaptionMessage",
    "editedMessage",
)
_MEDIA_KINDS: dict[str, MessageKind] = {
    "audioMessage": MessageKind.AUDIO,
    "imageMessage": MessageKind.IMAGEM,
    "videoMessage": MessageKind.VIDEO,
    "ptvMessage": MessageKind.VIDEO,
    "documentMessage": MessageKind.DOCUMENTO,
    "stickerMessage": MessageKind.FIGURINHA,
    "contactMessage": MessageKind.CONTATO,
    "contactsArrayMessage": MessageKind.CONTATO,
    "locationMessage": MessageKind.LOCALIZACAO,
    "liveLocationMessage": MessageKind.LOCALIZACAO,
}
_SELLER_REVOKED_WARNING = (
    "O vendedor apagou mensagem para todos no WhatsApp. O Radar guardou o texto original, marcado "
    "como apagado."
)
_STATES = {
    "open": WhatsAppState.CONECTADO,
    "connecting": WhatsAppState.AGUARDANDO_QR,
    "close": WhatsAppState.DESCONECTADO,
    "refused": WhatsAppState.DESCONECTADO,
}


@dataclass(frozen=True, slots=True)
class ConnectionRef:
    id: uuid.UUID
    tenant_id: uuid.UUID
    seller_id: uuid.UUID
    instance_name: str


# ---------------------------------------------------------------- leitura do payload
def event_name(body: Mapping[str, Any]) -> str:
    """``messages.upsert``, ``connection.update``… (a Evolution também manda ``MESSAGES_UPSERT``)."""
    return str(body.get("event") or "").strip().lower().replace("_", ".")


def contact_of(key: Mapping[str, Any]) -> str | None:
    """Telefone do contato (``+5511…``), ``lid:…`` sem telefone, ou ``None`` para grupo/status."""
    jid = str(key.get("remoteJid") or "")
    user, _, server = jid.partition("@")
    if not user or server.startswith(_SKIPPED_SERVERS) or user == "status":
        return None
    for candidate in (jid, str(key.get("remoteJidAlt") or ""), str(key.get("senderPn") or "")):
        number, _, domain = candidate.partition("@")
        number = number.split(":", 1)[0]
        if domain == "s.whatsapp.net" and number.isdigit():
            return f"+{number}"
    if server == "lid":
        return f"lid:{user.split(':', 1)[0]}"
    return None


def _unwrap(message: Any) -> dict[str, Any]:
    current = message if isinstance(message, dict) else {}
    for _ in range(4):
        for wrapper in _WRAPPERS:
            inner = current.get(wrapper)
            if isinstance(inner, dict) and isinstance(inner.get("message"), dict):
                current = inner["message"]
                break
        else:
            return current
    return current


def content_of(message: Any) -> tuple[MessageKind, str] | None:
    """Tipo e texto (ou legenda). ``None`` para o que não é conversa (reação, enquete…)."""
    body = _unwrap(message)
    if isinstance(body.get("conversation"), str):
        return MessageKind.TEXTO, body["conversation"]
    extended = body.get("extendedTextMessage")
    if isinstance(extended, dict) and isinstance(extended.get("text"), str):
        return MessageKind.TEXTO, extended["text"]
    for field, kind in _MEDIA_KINDS.items():
        part = body.get(field)
        if isinstance(part, dict):
            # Nome de arquivo costuma ter dado pessoal; só a legenda entra como texto.
            caption = part.get("caption")
            return kind, caption if isinstance(caption, str) else ""
    for field, text_key in (
        ("buttonsResponseMessage", "selectedDisplayText"),
        ("templateButtonReplyMessage", "selectedDisplayText"),
        ("listResponseMessage", "title"),
    ):
        part = body.get(field)
        if isinstance(part, dict) and isinstance(part.get(text_key), str):
            return MessageKind.TEXTO, part[text_key]
    return None


def protocol_of(message: Any) -> tuple[str, str, Any] | None:
    """``("apagar", id_alvo, None)`` ou ``("editar", id_alvo, mensagem_nova)``."""
    body = message if isinstance(message, dict) else {}
    proto = body.get("protocolMessage")
    if not isinstance(proto, dict):
        proto = _unwrap(body).get("protocolMessage")
    if not isinstance(proto, dict):
        return None
    target_key = proto.get("key")
    target = str(target_key.get("id") or "") if isinstance(target_key, dict) else ""
    if not target:
        return None
    kind = proto.get("type")
    if kind in ("REVOKE", 0):
        return "apagar", target, None
    if kind in ("MESSAGE_EDIT", 14):
        return "editar", target, proto.get("editedMessage")
    return None


def timestamp_of(value: Any) -> datetime:
    if isinstance(value, dict):  # Long do protobuf: {"low": ..., "high": ...}
        value = value.get("low")
    try:
        seconds = int(str(value))
    except (TypeError, ValueError):
        return utcnow()
    if seconds > 10**12:  # milissegundos
        seconds //= 1000
    return datetime.fromtimestamp(seconds, UTC) if seconds > 0 else utcnow()


def conversation_key(connection_id: uuid.UUID, contact_hash: str) -> str:
    """``external_id`` da conversa: vendedor (conexão) + contato, sem o telefone em claro."""
    return f"wa:{connection_id.hex}:{contact_hash[:48]}"


def parse_conversation_key(external_id: str | None) -> tuple[uuid.UUID, str] | None:
    if not external_id or not external_id.startswith("wa:"):
        return None
    parts = external_id.split(":", 2)
    if len(parts) != 3:
        return None
    _, connection, contact = parts
    try:
        return uuid.UUID(hex=connection), contact
    except ValueError:
        return None


# ---------------------------------------------------------------- entrada do webhook
def handle_event(
    body: Mapping[str, Any], settings: Settings, evolution: EvolutionClient | None
) -> str:
    """Trata um evento do webhook. Devolve o que aconteceu (para log e testes)."""
    event = event_name(body)
    instance = str(body.get("instance") or "")
    with session_scope() as db:
        row = db.scalar(
            select(WhatsAppConnection).where(WhatsAppConnection.instance_name == instance)
        )
        if row is None:
            return "instancia_desconhecida"
        connection = ConnectionRef(row.id, row.tenant_id, row.seller_id, row.instance_name)

    data = body.get("data")
    items = [
        item for item in (data if isinstance(data, list) else [data]) if isinstance(item, dict)
    ]
    if event == "connection.update":
        return _connection_update(connection, items[0] if items else {})
    outcomes: list[str] = []
    for item in items:
        if event == "messages.upsert":
            outcomes.append(_upsert(connection, item, settings, evolution))
        elif event == "messages.delete":
            key = item.get("key") if isinstance(item.get("key"), dict) else item
            target = str(key.get("id") or "") if isinstance(key, dict) else ""
            outcomes.append(_revoke(connection, target) if target else "ignorada")
        elif event in ("messages.edited", "messages.update"):
            outcomes.append(_update(connection, item))
        else:
            outcomes.append("ignorada")
    return ",".join(outcomes) or "ignorada"


def _upsert(
    connection: ConnectionRef,
    item: Mapping[str, Any],
    settings: Settings,
    evolution: EvolutionClient | None,
) -> str:
    key = item.get("key")
    if not isinstance(key, dict):
        return "ignorada"
    message = item.get("message")
    protocol = protocol_of(message)
    if protocol is not None:
        action, target, new_message = protocol
        return (
            _revoke(connection, target)
            if action == "apagar"
            else _edit(connection, target, new_message)
        )
    contact = contact_of(key)
    if contact is None:
        return "ignorada:grupo_ou_status"
    content = content_of(message)
    message_id = str(key.get("id") or "")
    if content is None or not message_id:
        return "ignorada:tipo"
    kind, text = content
    from_me = bool(key.get("fromMe"))

    with session_scope(connection.tenant_id) as db:
        tenant = db.get(Tenant, connection.tenant_id)
        seller = db.get(Seller, connection.seller_id)
        if tenant is None or seller is None:
            return "ignorada:vendedor_removido"
        contact_hash = subject_hash(tenant.id, contact)
        ignored = db.scalar(
            select(WhatsAppIgnoredContact.id).where(
                WhatsAppIgnoredContact.connection_id == connection.id,
                WhatsAppIgnoredContact.contact_hash == contact_hash,
            )
        )
        if ignored is not None:
            return "ignorada:contato_removido"
        seller_author = seller.display_name
        customer_author = contact if contact != seller_author else f"{contact} (cliente)"
        participants = {
            seller_author: ParticipantInfo(
                seller_author, SenderRole.VENDEDOR, seller.id, "alta", "WhatsApp conectado"
            ),
            customer_author: ParticipantInfo(
                customer_author, SenderRole.CLIENTE, None, "alta", "WhatsApp conectado"
            ),
        }
        incoming = IncomingMessage(
            sent_at=timestamp_of(item.get("messageTimestamp")),
            author=seller_author if from_me else customer_author,
            text=text.strip(),
            kind=kind,
            external_id=message_id,
        )
        result = ingest_conversation(
            db,
            tenant=tenant,
            source=ImportSource.EVOLUTION,
            participants=participants,
            messages=[incoming],
            external_id=conversation_key(connection.id, contact_hash),
        )
        if not result.new_messages:
            return "repetida"
        row = result.new_messages[0]
        if kind is MessageKind.AUDIO:
            _store_audio(db, row, connection, item, settings, evolution)
        # Não analisa a cada mensagem: espera a conversa dar uma pausa.
        result.conversation.status = ConversationStatus.AGUARDANDO
        conversation_id = result.conversation.id
    # Já transcreve e mascara, para o texto aparecer no painel enquanto a conversa acontece.
    enqueue_prepare(conversation_id, connection.tenant_id)
    return "gravada"


def _store_audio(
    db: Session,
    row: Message,
    connection: ConnectionRef,
    item: Mapping[str, Any],
    settings: Settings,
    evolution: EvolutionClient | None,
) -> None:
    """Baixa o áudio na hora (o link do WhatsApp expira) para transcrever na análise."""
    row.transcription_status = TranscriptionStatus.IGNORADA
    if evolution is None:
        return
    try:
        content, mimetype = evolution.media(
            connection.instance_name, {"key": item.get("key"), "message": item.get("message")}
        )
    except EvolutionError as exc:
        log.warning("whatsapp_audio_nao_baixado", message_id=str(row.id), erro=str(exc))
        return
    lowered = mimetype.lower()
    ext = (
        "ogg"
        if "ogg" in lowered or "opus" in lowered
        else "m4a"
        if "mp4" in lowered or "aac" in lowered
        else "mp3"
        if "mpeg" in lowered
        else "bin"
    )
    destination = (
        settings.media_dir
        / str(row.tenant_id)
        / str(row.conversation_id)
        / f"{uuid.uuid4().hex}.{ext}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    row.media_path = relative_to_data(destination, settings)
    row.transcription_status = TranscriptionStatus.PENDENTE
    db.flush()


def _find_message(db: Session, connection: ConnectionRef, target: str) -> Message | None:
    return db.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.dedupe_hash == external_message_hash(target),
            Conversation.source == ImportSource.EVOLUTION,
            Conversation.external_id.startswith(f"wa:{connection.id.hex}:"),
        )
    )


def _revoke(connection: ConnectionRef, target: str) -> str:
    with session_scope(connection.tenant_id) as db:
        row = _find_message(db, connection, target)
        if row is None:
            return "apagada:desconhecida"
        if row.revoked_at is not None:
            return "apagada:repetida"
        row.revoked_at = utcnow()
        if row.sender_role is SenderRole.VENDEDOR:
            conversation = db.get(Conversation, row.conversation_id)
            if conversation is not None and _SELLER_REVOKED_WARNING not in (
                conversation.warnings or []
            ):
                conversation.warnings = [*(conversation.warnings or []), _SELLER_REVOKED_WARNING]
    return "apagada"


def _edit(connection: ConnectionRef, target: str, new_message: Any) -> str:
    content = content_of(new_message)
    new_text = content[1].strip() if content else ""
    if not new_text:
        return "editada:sem_texto"
    with session_scope(connection.tenant_id) as db:
        row = _find_message(db, connection, target)
        if row is None:
            return "editada:desconhecida"
        original = row.text_raw or ""
        marker = f"[editada no WhatsApp para: {new_text}]"
        if marker in original:
            return "editada:repetida"
        # O original fica: o cliente leu primeiro a versão antiga.
        row.text_raw = f"{original}\n{marker}" if original else marker
        row.edited = True
        row.text_masked = None
        row.pii_spans = []
        conversation_id = row.conversation_id
        conversation = db.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.status = ConversationStatus.AGUARDANDO
    enqueue_prepare(conversation_id, connection.tenant_id)
    return "editada"


def _update(connection: ConnectionRef, item: Mapping[str, Any]) -> str:
    """``messages.update`` / ``messages.edited``: só interessam edição e "apagar para todos"."""
    protocol = protocol_of(item.get("message"))
    if protocol is None:
        update_part = item.get("update")
        if isinstance(update_part, dict):
            protocol = protocol_of(update_part.get("message"))
    if protocol is not None:
        action, target, new_message = protocol
        return (
            _revoke(connection, target)
            if action == "apagar"
            else _edit(connection, target, new_message)
        )
    if str(item.get("status") or "").upper() == "DELETED":
        key = item.get("key")
        target = str(item.get("keyId") or (key.get("id") if isinstance(key, dict) else "") or "")
        return _revoke(connection, target) if target else "ignorada"
    return "ignorada:status"


def _connection_update(connection: ConnectionRef, data: Mapping[str, Any]) -> str:
    new_state = _STATES.get(str(data.get("state") or "").lower())
    if new_state is None:
        return "ignorada"
    with session_scope(connection.tenant_id) as db:
        row = db.get(WhatsAppConnection, connection.id)
        if row is None:
            return "ignorada"
        apply_state(db, row, new_state, phone_jid=str(data.get("wuid") or ""))
    return f"conexao:{new_state.value}"


def apply_state(
    db: Session, row: WhatsAppConnection, new_state: WhatsAppState, *, phone_jid: str = ""
) -> None:
    """Atualiza o estado; conectar e cair ficam na auditoria (a gestão vê quem saiu do ar)."""
    now = utcnow()
    row.last_event_at = now
    if new_state is WhatsAppState.AGUARDANDO_QR and row.state is WhatsAppState.CONECTADO:
        return  # reconexão rápida de uma sessão que já estava aberta
    digits = "".join(ch for ch in phone_jid.split("@", 1)[0].split(":", 1)[0] if ch.isdigit())
    if digits:
        row.phone_tail = digits[-4:]
    if new_state is row.state:
        return
    if new_state is WhatsAppState.CONECTADO:
        row.connected_at = now
        action = AuditAction.WHATSAPP_CONNECTED
    elif new_state is WhatsAppState.DESCONECTADO and row.state is WhatsAppState.CONECTADO:
        row.disconnected_at = now
        action = AuditAction.WHATSAPP_DISCONNECTED
    else:
        action = ""
    row.state = new_state
    if action:
        record_audit(
            db,
            tenant_id=row.tenant_id,
            action=action,
            actor_label="WhatsApp",
            resource_type="seller",
            resource_id=row.seller_id,
            details={"final_do_numero": row.phone_tail},
        )


def refresh_state(db: Session, row: WhatsAppConnection, evolution: EvolutionClient) -> None:
    """Confere o estado na Evolution (caso um webhook tenha se perdido)."""
    try:
        state = evolution.state(row.instance_name, timeout=3)
    except EvolutionError:
        return
    apply_state(db, row, _STATES.get(state or "", WhatsAppState.DESCONECTADO))


def ignore_contact(db: Session, conversation: Conversation) -> bool:
    """Para de capturar o contato desta conversa (só conversas do WhatsApp conectado)."""
    parsed = parse_conversation_key(conversation.external_id)
    if conversation.source is not ImportSource.EVOLUTION or parsed is None:
        return False
    connection_id, contact_prefix = parsed
    connection = db.get(WhatsAppConnection, connection_id)
    # O hash completo do contato é o customer_hash da conversa (a chave guarda só o começo).
    full_hash = conversation.customer_hash or ""
    if connection is None or not contact_prefix or not full_hash.startswith(contact_prefix):
        return False
    exists = db.scalar(
        select(WhatsAppIgnoredContact.id).where(
            WhatsAppIgnoredContact.connection_id == connection.id,
            WhatsAppIgnoredContact.contact_hash == full_hash,
        )
    )
    if exists is None:
        db.add(
            WhatsAppIgnoredContact(
                tenant_id=conversation.tenant_id,
                connection_id=connection.id,
                contact_hash=full_hash,
            )
        )
    return True


# ---------------------------------------------------------------- análise depois da pausa
def enqueue_idle_conversations(settings: Settings, now: datetime | None = None) -> int:
    """Manda analisar as conversas ao vivo que deram uma pausa (ou que não param há horas)."""
    from radar.worker.jobs import enqueue_conversation

    now = now or utcnow()
    idle_before = now - timedelta(minutes=settings.whatsapp_idle_minutes)
    stale_before = now - timedelta(minutes=settings.whatsapp_max_wait_minutes)
    with session_scope() as db:
        rows = db.execute(
            select(
                Conversation.id,
                Conversation.tenant_id,
                Conversation.last_message_at,
                Conversation.analyzed_at,
                Conversation.started_at,
            ).where(
                Conversation.source == ImportSource.EVOLUTION,
                Conversation.status == ConversationStatus.AGUARDANDO,
            )
        ).all()
        due = [
            (conversation_id, tenant_id)
            for conversation_id, tenant_id, last, analyzed, started in rows
            if last is None or last <= idle_before or (analyzed or started or now) <= stale_before
        ]
        if due:
            db.execute(
                update(Conversation)
                .where(Conversation.id.in_([conversation_id for conversation_id, _ in due]))
                .values(status=ConversationStatus.PENDENTE)
                .execution_options(synchronize_session=False)
            )
    for conversation_id, tenant_id in due:
        enqueue_conversation(conversation_id, tenant_id)
    if due:
        log.info("whatsapp_analises_enfileiradas", conversas=len(due))
    return len(due)


def instance_name_for(seller_id: uuid.UUID) -> str:
    """Nome da instância na Evolution: estável por vendedor, sem dado pessoal."""
    return "radar-" + hashlib.sha256(seller_id.bytes).hexdigest()[:20]
