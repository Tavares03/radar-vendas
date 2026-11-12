# syntax=docker/dockerfile:1.7
# Imagem única para API, worker e agendador. Contexto de build: a raiz do repositório.
#   docker build -f backend/Dockerfile -t radar-vendas-backend .

# ---------------------------------------------------------------- builder
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# 1) Só os manifestos: a camada de dependências fica em cache enquanto o lock não mudar.
COPY pyproject.toml uv.lock .python-version ./
COPY backend/pyproject.toml backend/README.md backend/
COPY synthetic/pyproject.toml synthetic/README.md synthetic/
COPY evals/pyproject.toml evals/README.md evals/
COPY training/pyproject.toml training/README.md training/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package radar-vendas

# 2) O código do backend.
COPY backend/src backend/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package radar-vendas

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Radar de Vendas (backend)" \
      org.opencontainers.image.description="API, worker e agendador do Radar de Vendas" \
      org.opencontainers.image.source="https://github.com/Tavares03/radar-vendas" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --system --gid 10001 radar \
    && useradd --system --uid 10001 --gid radar --home-dir /home/radar --create-home radar \
    && mkdir -p /data /models /cache/hf \
    && chown -R radar:radar /data /models /cache

WORKDIR /app

COPY --from=builder --chown=radar:radar /app/.venv /app/.venv
COPY --chown=radar:radar backend/alembic.ini backend/alembic.ini
COPY --chown=radar:radar backend/migrations backend/migrations
COPY --chown=radar:radar playbooks playbooks
COPY --chown=radar:radar data/samples data/samples

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RADAR_DATA_DIR=/data \
    RADAR_MODELS_DIR=/models \
    RADAR_PLAYBOOKS_DIR=/app/playbooks \
    RADAR_SAMPLES_DIR=/app/data/samples \
    HF_HOME=/cache/hf

USER radar
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

# Os cabeçalhos X-Forwarded-* só são aceitos dos IPs em FORWARDED_ALLOW_IPS (padrão: 127.0.0.1).
CMD ["uvicorn", "--factory", "radar.api.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
