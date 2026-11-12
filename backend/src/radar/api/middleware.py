"""Middleware ASGI: id de requisição, contexto de log, métricas e cabeçalhos de segurança."""

from __future__ import annotations

import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radar.logs import bind_context, clear_context, get_logger
from radar.observability import HTTP_DURATION, HTTP_REQUESTS

log = get_logger("radar.http")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATHS = ("/api/health", "/api/ready", "/api/metrics")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
    "Cache-Control": "no-store",
}


def route_template(scope: Scope) -> str:
    """Caminho da rota com os parâmetros de volta ao nome, ex.: ``/api/v1/users/{user_id}``.

    Serve de rótulo de métrica: usar o caminho cru criaria uma série por id. O modelo é
    reconstruído a partir de ``path_params`` para não depender de como os routers são aninhados.
    """
    if scope.get("endpoint") is None:
        return "nao_roteado"
    path: str = scope.get("path", "")
    params = scope.get("path_params") or {}
    if not params:
        return path
    by_value = {str(value).lower(): name for name, value in params.items()}
    return "/".join(
        f"{{{by_value[segment.lower()]}}}" if segment.lower() in by_value else segment
        for segment in path.split("/")
    )


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        clear_context()
        bind_context(request_id=request_id)

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            path: str = scope.get("path", "")
            route_path = route_template(scope)
            method: str = scope.get("method", "")
            HTTP_REQUESTS.labels(method=method, route=route_path, status=str(status_code)).inc()
            HTTP_DURATION.labels(method=method, route=route_path).observe(elapsed)
            if not path.startswith(_QUIET_PATHS):
                log.info(
                    "http_request",
                    method=method,
                    path=path,
                    status=status_code,
                    duration_ms=round(elapsed * 1000, 1),
                )
            clear_context()
