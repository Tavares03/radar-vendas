"""Aplicação FastAPI.

Suba com ``uvicorn --factory radar.api.app:create_app``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from radar import __version__
from radar.api.errors import install_error_handlers
from radar.api.middleware import BodyLimitMiddleware, RequestContextMiddleware
from radar.api.routers import (
    alerts,
    api_tokens,
    audit,
    auth,
    conversations,
    health,
    imports,
    insights,
    playbooks,
    privacy,
    removals,
    sellers,
    tenant,
    users,
    whatsapp,
)
from radar.config import DEV_SECRET_KEY, get_settings
from radar.logs import configure_logging, get_logger
from radar.runtime import prepare_runtime

DESCRIPTION = """
API do **Radar de Vendas**, um supervisor de vendas com IA para equipes que vendem pelo WhatsApp.

**Autenticação.** Use `Authorization: Bearer <token>`, onde o token é:

- um token de sessão, devolvido por `POST /api/v1/auth/login`; ou
- um token de API (`rdr_...`), criado em *Configurações → Integrações*, para sistemas externos.

**Isolamento.** Toda resposta contém apenas dados da empresa dona do token.

**Erros.** Sempre no formato `{"error": {"code", "message", "details"}}`.
"""

#: Limite do corpo fora das rotas de upload (JSON de conversas, playbooks…).
MAX_JSON_BODY_MB = 10

TAGS = [
    {"name": "visão geral", "description": "Indicadores da empresa e de cada vendedor."},
    {"name": "saúde", "description": "Liveness, readiness e métricas."},
    {"name": "autenticação", "description": "Login, sessão e senha."},
    {"name": "empresa", "description": "Dados e configurações da empresa."},
    {"name": "usuários", "description": "Usuários e papéis."},
    {"name": "vendedores", "description": "Cadastro de vendedores."},
    {"name": "importação", "description": "Envio de conversas exportadas do WhatsApp."},
    {"name": "conversas", "description": "Conversas, mensagens e envio por API."},
    {
        "name": "privacidade",
        "description": "LGPD: localizar, exportar e excluir dados de um titular; retenção.",
    },
    {"name": "alertas", "description": "Fila de alertas: riscos e oportunidades com evidência."},
    {"name": "playbooks", "description": "Regras por setor em YAML, padrão ou da empresa."},
    {"name": "integrações", "description": "Tokens de API, webhooks e canais de alerta."},
    {
        "name": "whatsapp",
        "description": "WhatsApp conectado por QR code (Evolution API): estado e conexão.",
    },
    {"name": "auditoria", "description": "Trilha de auditoria."},
]


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.json_logs)
    log = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.secret_key.get_secret_value() == DEV_SECRET_KEY:
            log.warning(
                "secret_key_de_desenvolvimento",
                aviso="Defina RADAR_SECRET_KEY antes de expor esta instalação.",
            )
        prepare_runtime(settings)
        log.info(
            "api_iniciada",
            version=__version__,
            environment=settings.environment,
            queue_mode=settings.queue_mode,
            llm_mode=settings.llm_mode,
        )
        yield

    app = FastAPI(
        title="Radar de Vendas API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        license_info={"name": "Apache-2.0", "identifier": "Apache-2.0"},
    )

    # O último middleware adicionado é o mais externo: o limite de corpo fica por dentro do
    # contexto de requisição, para que a recusa também ganhe X-Request-ID, log e métrica.
    megabyte = 1024 * 1024
    app.add_middleware(
        BodyLimitMiddleware,
        default_limit=MAX_JSON_BODY_MB * megabyte,
        # Folga para os cabeçalhos do multipart em torno de um arquivo do tamanho máximo.
        upload_limit=settings.max_upload_mb * megabyte + megabyte,
        upload_paths=("/api/v1/imports",),
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Retry-After"],
        )
    install_error_handlers(app)

    app.include_router(health.router, prefix="/api")

    v1 = APIRouter(prefix="/api/v1")
    for module in (
        auth,
        tenant,
        users,
        sellers,
        imports,
        conversations,
        alerts,
        insights,
        playbooks,
        privacy,
        removals,
        whatsapp,
        api_tokens,
        audit,
    ):
        v1.include_router(module.router)
    v1.include_router(whatsapp.webhook_router)
    app.include_router(v1)
    return app
