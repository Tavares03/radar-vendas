"""Saúde do serviço e métricas."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from radar import __version__
from radar.api.deps import DbDep, SettingsDep
from radar.api.errors import NotFound, ServiceUnavailable, Unauthorized
from radar.observability import REGISTRY

router = APIRouter(tags=["saúde"])


@router.get("/health", summary="Liveness: o processo está de pé")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/ready", summary="Readiness: banco e fila respondem")
def ready(db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"erro: {type(exc).__name__}"
    if settings.queue_mode == "rq":
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_timeout=2).ping()
            checks["queue"] = "ok"
        except Exception as exc:
            checks["queue"] = f"erro: {type(exc).__name__}"
    else:
        checks["queue"] = settings.queue_mode
    if any(value.startswith("erro") for value in checks.values()):
        raise ServiceUnavailable("Dependência indisponível.", details=checks)
    return {"status": "ok", "checks": checks}


@router.get("/metrics", summary="Métricas Prometheus", include_in_schema=False)
def metrics(request: Request, settings: SettingsDep) -> Response:
    token = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if token:
        header = request.headers.get("authorization", "")
        supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied, token):
            raise Unauthorized("Token de métricas inválido.")
    elif settings.environment == "prod":
        # Em produção as métricas só existem se RADAR_METRICS_TOKEN estiver definido.
        raise NotFound("Não encontrado.")
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
