"""Schemas do WhatsApp conectado."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from radar.api.schemas.common import ApiModel
from radar.api.schemas.conversations import SellerBrief
from radar.taxonomy import WhatsAppState


class WhatsAppConnectionOut(ApiModel):
    id: uuid.UUID
    state: WhatsAppState
    #: Os 4 últimos dígitos do número conectado.
    phone_tail: str
    connected_at: datetime | None
    #: Quando o número saiu do ar (desconectado no celular ou pela gestão).
    disconnected_at: datetime | None
    last_event_at: datetime | None


class WhatsAppSellerOut(BaseModel):
    seller: SellerBrief
    connection: WhatsAppConnectionOut | None


class WhatsAppStatusOut(BaseModel):
    #: A integração está configurada (``RADAR_EVOLUTION_URL``).
    enabled: bool
    #: A Evolution API respondeu agora.
    available: bool
    #: Quem pergunta vê e desconecta a equipe toda (gestão) ou só conecta o próprio número.
    can_manage: bool
    #: Minutos sem mensagem nova até a conversa ser analisada.
    idle_minutes: int
    sellers: list[WhatsAppSellerOut]


class WhatsAppQrOut(BaseModel):
    state: WhatsAppState
    #: QR code em data URL (PNG). Vazio quando o número já está conectado.
    qr_image: str | None = None
    #: Código para "conectar com número de telefone", quando disponível.
    pairing_code: str | None = None
