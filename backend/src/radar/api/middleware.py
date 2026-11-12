"""Middleware ASGI: id de requisição, contexto de log, métricas e cabeçalhos de segurança."""

from __future__ import annotations

import json
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


class _BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Recusa corpos maiores do que o limite, antes de a aplicação gastar memória ou disco.

    Confere o ``Content-Length`` e, como ele pode faltar ou mentir, também conta os bytes que
    chegam de fato.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_limit: int,
        upload_limit: int,
        upload_paths: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.default_limit = default_limit
        self.upload_limit = upload_limit
        self.upload_paths = upload_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        limit = self.upload_limit if path.startswith(self.upload_paths) else self.default_limit
        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            await self._reject(send, limit)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if started:
                raise
            await self._reject(send, limit)

    @staticmethod
    async def _reject(send: Send, limit: int) -> None:
        megabytes = max(1, limit // (1024 * 1024))
        body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": f"O envio passa do limite de {megabytes} MB.",
                }
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


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
