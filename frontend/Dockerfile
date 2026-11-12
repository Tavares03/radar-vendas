# syntax=docker/dockerfile:1.7
# Painel do Radar de Vendas (Next.js, saída standalone). Contexto de build: a pasta frontend/.

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

FROM node:24-alpine AS builder
WORKDIR /app
# O destino do proxy /api é fixado no build (as regras de rewrite entram no manifesto de rotas).
ARG BACKEND_URL=http://api:8000
ENV BACKEND_URL=${BACKEND_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-alpine AS runtime
LABEL org.opencontainers.image.title="Radar de Vendas (painel)" \
      org.opencontainers.image.source="https://github.com/Tavares03/radar-vendas" \
      org.opencontainers.image.licenses="Apache-2.0"
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S radar && adduser -S radar -G radar
COPY --from=builder --chown=radar:radar /app/.next/standalone ./
COPY --from=builder --chown=radar:radar /app/.next/static ./.next/static
COPY --from=builder --chown=radar:radar /app/public ./public
USER radar
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/login || exit 1
CMD ["node", "server.js"]
