"""Cliente da Evolution API: conecta números de WhatsApp como um "aparelho" (igual ao WhatsApp Web).

O Radar só **lê**: cria a instância, mostra o QR code, consulta o estado, baixa o áudio de uma
mensagem para transcrever e desconecta. Nunca envia mensagens.

Atenção: a Evolution usa o protocolo do WhatsApp Web sem ser um cliente oficial, o que vai contra
os termos do WhatsApp; o número pode ser banido. Ver ``docs/DECISOES.md`` (D54).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx

from radar.config import Settings
from radar.logs import get_logger

log = get_logger(__name__)

#: Eventos que a Evolution manda para o webhook do Radar.
WEBHOOK_EVENTS = (
    "MESSAGES_UPSERT",
    "MESSAGES_UPDATE",
    "MESSAGES_DELETE",
    "MESSAGES_EDITED",
    "CONNECTION_UPDATE",
)
#: Teto de um áudio baixado (uma nota de voz de 30 min em opus tem poucos MB).
MAX_MEDIA_BYTES = 40 * 1024 * 1024


class EvolutionError(RuntimeError):
    """A Evolution API não respondeu ou recusou o pedido."""


@dataclass(frozen=True, slots=True)
class QrCode:
    #: Imagem PNG em data URL (``data:image/png;base64,...``); ``None`` se já está conectado.
    image: str | None
    #: Código para "conectar com número de telefone", quando a Evolution devolve um.
    pairing_code: str | None


def webhook_token(settings: Settings) -> str:
    """Segredo do endereço do webhook, derivado de ``RADAR_SECRET_KEY`` (estável entre reinícios)."""
    key = settings.secret_key.get_secret_value().encode()
    return hmac.new(key, b"radar:evolution-webhook", hashlib.sha256).hexdigest()[:40]


def webhook_url(settings: Settings) -> str:
    base = settings.evolution_webhook_base_url.rstrip("/")
    return f"{base}/api/v1/integrations/evolution/webhook/{webhook_token(settings)}"


class EvolutionClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 15.0,
        http: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"apikey": api_key}
        self._http = http or httpx.Client(timeout=timeout)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        timeout: float | None = None,
        missing_ok: bool = False,
    ) -> Any:
        """Chama a Evolution. Com ``missing_ok``, um 404 (instância inexistente) devolve ``None``."""
        url = f"{self._base}{path}"
        try:
            if timeout is None:
                response = self._http.request(method, url, json=json, headers=self._headers)
            else:
                response = self._http.request(
                    method, url, json=json, headers=self._headers, timeout=timeout
                )
        except httpx.HTTPError as exc:
            raise EvolutionError(
                f"Evolution API fora do ar ({type(exc).__name__}). Ela sobe com "
                "`docker compose --profile whatsapp up`."
            ) from exc
        if response.status_code == 401:
            raise EvolutionError(
                "A Evolution API recusou a chave: confira RADAR_EVOLUTION_API_KEY e "
                "EVOLUTION_API_KEY."
            )
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code >= 400:
            raise EvolutionError(f"Evolution API respondeu HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------ instância
    def available(self) -> bool:
        try:
            self._request("GET", "/", timeout=3)
        except EvolutionError:
            return False
        return True

    def create_instance(self, name: str, *, webhook: str) -> None:
        self._request(
            "POST",
            "/instance/create",
            json={
                "instanceName": name,
                "integration": "WHATSAPP-BAILEYS",
                "qrcode": True,
                # Grupos nunca entram; o Radar não marca nada como lido nem fica "online".
                "groupsIgnore": True,
                "alwaysOnline": False,
                "readMessages": False,
                "readStatus": False,
                # Só o que chegar depois de conectar: o histórico antigo do número (inclusive
                # pessoal) não é importado. Conversas antigas entram pelo export.
                "syncFullHistory": False,
                "rejectCall": False,
                "webhook": {
                    "url": webhook,
                    "byEvents": False,
                    "base64": False,
                    "events": list(WEBHOOK_EVENTS),
                },
            },
        )

    def qr_code(self, name: str) -> QrCode:
        data = self._request("GET", f"/instance/connect/{name}")
        image = data.get("base64") if isinstance(data, dict) else None
        pairing = data.get("pairingCode") if isinstance(data, dict) else None
        return QrCode(
            image=image if isinstance(image, str) and image.startswith("data:image") else None,
            pairing_code=pairing if isinstance(pairing, str) and pairing else None,
        )

    def state(self, name: str, *, timeout: float | None = None) -> str | None:
        """``open``, ``connecting`` ou ``close``; ``None`` se a instância não existe."""
        # Instância que nunca existiu dá 404; recém-apagada, 200 sem "state". As duas: None.
        data = self._request(
            "GET", f"/instance/connectionState/{name}", timeout=timeout, missing_ok=True
        )
        instance = data.get("instance") if isinstance(data, dict) else None
        state = instance.get("state") if isinstance(instance, dict) else None
        return state if isinstance(state, str) else None

    def disconnect(self, name: str) -> None:
        """Desconecta o número e apaga a instância (a sessão do WhatsApp deixa de existir)."""
        for path in (f"/instance/logout/{name}", f"/instance/delete/{name}"):
            try:
                self._request("DELETE", path, missing_ok=True)
            except EvolutionError as exc:
                log.info("evolution_desconexao_parcial", instancia=name, etapa=path, erro=str(exc))

    # ------------------------------------------------------------ mídia
    def media(self, name: str, message: dict[str, Any]) -> tuple[bytes, str]:
        """Baixa a mídia de uma mensagem (o objeto como veio no webhook). Devolve bytes e tipo."""
        data = self._request(
            "POST",
            f"/chat/getBase64FromMediaMessage/{name}",
            json={"message": message, "convertToMp4": False},
            timeout=60,
        )
        encoded = data.get("base64") if isinstance(data, dict) else None
        if not isinstance(encoded, str) or not encoded:
            raise EvolutionError("a Evolution não devolveu a mídia")
        if len(encoded) > MAX_MEDIA_BYTES * 4 // 3 + 4:
            raise EvolutionError("mídia grande demais")
        try:
            content = base64.b64decode(encoded.split(",", 1)[-1], validate=False)
        except (binascii.Error, ValueError) as exc:
            raise EvolutionError("mídia em formato inesperado") from exc
        mimetype = data.get("mimetype") if isinstance(data, dict) else None
        return content, str(mimetype or "")


# ---------------------------------------------------------------- instância compartilhada
_override: EvolutionClient | None = None
_has_override = False


def set_evolution_client(client: EvolutionClient | None, *, clear: bool = False) -> None:
    """Troca o cliente (testes). ``clear=True`` volta a montar pela configuração."""
    global _override, _has_override
    _override, _has_override = (None, False) if clear else (client, True)


def get_evolution(settings: Settings) -> EvolutionClient | None:
    """O cliente configurado, ou ``None`` se a integração está desligada."""
    if _has_override:
        return _override
    if not settings.evolution_url or settings.evolution_api_key is None:
        return None
    return EvolutionClient(settings.evolution_url, settings.evolution_api_key.get_secret_value())
