"""WhatsApp conectado (Evolution API): conectar por QR code, ver o estado e receber mensagens.

- O vendedor conecta **o próprio** número; a gestão vê a equipe toda e é quem desconecta.
- O webhook recebe os eventos da Evolution. Não usa sessão: o endereço tem um segredo derivado
  de ``RADAR_SECRET_KEY`` e fica fora da documentação pública.
"""

from __future__ import annotations

import hmac
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from radar.api.deps import DbDep, SettingsDep, request_meta, require
from radar.api.errors import Forbidden, NotFound, ServiceUnavailable
from radar.api.schemas.conversations import SellerBrief
from radar.api.schemas.whatsapp import (
    WhatsAppConnectionOut,
    WhatsAppQrOut,
    WhatsAppSellerOut,
    WhatsAppStatusOut,
)
from radar.auth.principal import Permission, Principal
from radar.db.base import utcnow
from radar.db.models import Seller, WhatsAppConnection
from radar.integrations.evolution import EvolutionError, get_evolution, webhook_token, webhook_url
from radar.integrations.whatsapp import (
    apply_state,
    handle_event,
    instance_name_for,
    refresh_state,
)
from radar.logs import get_logger
from radar.services.audit import AuditAction, record_audit
from radar.taxonomy import WhatsAppState

log = get_logger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
webhook_router = APIRouter(prefix="/integrations/evolution", include_in_schema=False)

#: Conectar o próprio número exige o mesmo que enviar conversas.
ConnectDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_WRITE))]
ManageDep = Annotated[Principal, Depends(require(Permission.WHATSAPP_MANAGE))]


def _target_seller(db: DbDep, principal: Principal, seller_id: uuid.UUID) -> Seller:
    if not principal.can(Permission.WHATSAPP_MANAGE) and principal.only_seller_id != seller_id:
        raise Forbidden("Você só pode conectar o seu próprio WhatsApp.")
    seller = db.get(Seller, seller_id)
    if seller is None or not seller.is_active:
        raise NotFound("Vendedor não encontrado.")
    return seller


@router.get("", response_model=WhatsAppStatusOut, summary="Estado do WhatsApp da equipe")
def status(db: DbDep, settings: SettingsDep, principal: ConnectDep) -> WhatsAppStatusOut:
    """A gestão vê todos os vendedores; o vendedor vê só o próprio número."""
    evolution = get_evolution(settings)
    available = evolution.available() if evolution is not None else False
    can_manage = principal.can(Permission.WHATSAPP_MANAGE)
    query = select(Seller).where(Seller.is_active.is_(True)).order_by(Seller.display_name)
    if not can_manage:
        if principal.only_seller_id is None:
            query = query.where(Seller.id.is_(None))
        else:
            query = query.where(Seller.id == principal.only_seller_id)
    sellers = list(db.scalars(query))
    connections = {
        row.seller_id: row
        for row in db.scalars(
            select(WhatsAppConnection).where(
                WhatsAppConnection.seller_id.in_([s.id for s in sellers])
            )
        )
    }
    if available and evolution is not None:
        for row in connections.values():
            refresh_state(db, row, evolution)
        db.commit()
    return WhatsAppStatusOut(
        enabled=evolution is not None,
        available=available,
        can_manage=can_manage,
        idle_minutes=settings.whatsapp_idle_minutes,
        sellers=[
            WhatsAppSellerOut(
                seller=SellerBrief(id=seller.id, display_name=seller.display_name),
                connection=WhatsAppConnectionOut.model_validate(connections[seller.id])
                if seller.id in connections
                else None,
            )
            for seller in sellers
        ],
    )


@router.post(
    "/sellers/{seller_id}/connect",
    response_model=WhatsAppQrOut,
    summary="Conectar o WhatsApp de um vendedor (QR code)",
)
def connect(
    seller_id: uuid.UUID,
    db: DbDep,
    settings: SettingsDep,
    principal: ConnectDep,
) -> WhatsAppQrOut:
    """Devolve o QR code para ler em *WhatsApp → Aparelhos conectados*. Chamar de novo traz um
    QR novo (eles expiram em segundos)."""
    seller = _target_seller(db, principal, seller_id)
    evolution = get_evolution(settings)
    if evolution is None:
        raise ServiceUnavailable(
            "O WhatsApp ao vivo não está ligado nesta instalação. Suba com "
            "`docker compose --profile whatsapp up`."
        )
    row = db.scalar(select(WhatsAppConnection).where(WhatsAppConnection.seller_id == seller.id))
    if row is None:
        row = WhatsAppConnection(
            tenant_id=principal.tenant_id,
            seller_id=seller.id,
            instance_name=instance_name_for(seller.id),
            state=WhatsAppState.DESCONECTADO,
            created_by_user_id=principal.user_id,
        )
        db.add(row)
        db.flush()
    try:
        current = evolution.state(row.instance_name)
        if current is None:
            evolution.create_instance(row.instance_name, webhook=webhook_url(settings))
            current = "connecting"
        if current == "open":
            apply_state(db, row, WhatsAppState.CONECTADO)
            db.commit()
            return WhatsAppQrOut(state=row.state)
        qr = evolution.qr_code(row.instance_name)
    except EvolutionError as exc:
        db.rollback()
        raise ServiceUnavailable(str(exc)) from exc
    apply_state(db, row, WhatsAppState.AGUARDANDO_QR)
    db.commit()
    return WhatsAppQrOut(state=row.state, qr_image=qr.image, pairing_code=qr.pairing_code)


@router.delete(
    "/sellers/{seller_id}/connection",
    status_code=204,
    summary="Desconectar o WhatsApp de um vendedor",
)
def disconnect(
    seller_id: uuid.UUID,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: ManageDep,
) -> Response:
    """Só a gestão desconecta pelo painel. As conversas já recebidas ficam no Radar."""
    row = db.scalar(select(WhatsAppConnection).where(WhatsAppConnection.seller_id == seller_id))
    if row is None:
        raise NotFound("Este vendedor não tem WhatsApp conectado.")
    evolution = get_evolution(settings)
    if evolution is not None:
        evolution.disconnect(row.instance_name)
    if row.state is not WhatsAppState.DESCONECTADO:
        row.disconnected_at = utcnow()
    row.state = WhatsAppState.DESCONECTADO
    row.last_event_at = utcnow()
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.WHATSAPP_DISCONNECTED,
        principal=principal,
        resource_type="seller",
        resource_id=seller_id,
        details={"pela": "gestão", "final_do_numero": row.phone_tail},
        **request_meta(request),
    )
    db.commit()
    return Response(status_code=204)


@webhook_router.post("/webhook/{token}")
async def webhook(token: str, request: Request, settings: SettingsDep) -> dict[str, Any]:
    """Eventos da Evolution API (mensagens, edições, exclusões e estado da conexão)."""
    if not hmac.compare_digest(token, webhook_token(settings)):
        raise NotFound("Não encontrado.")
    try:
        body = json.loads(await request.body())
    except ValueError:
        return {"ok": False, "motivo": "json_invalido"}
    if not isinstance(body, dict):
        return {"ok": False, "motivo": "formato_inesperado"}
    # O tratamento abre sessões de banco e pode baixar áudio: roda fora do loop assíncrono.
    outcome = await run_in_threadpool(handle_event, body, settings, get_evolution(settings))
    log.debug("whatsapp_evento", resultado=outcome)
    return {"ok": True, "resultado": outcome}
