"""Métricas Prometheus do processo (API e worker)."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "radar_http_requests_total",
    "Requisições HTTP atendidas",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "radar_http_request_duration_seconds",
    "Duração das requisições HTTP",
    ["method", "route"],
    registry=REGISTRY,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
PIPELINE_STAGE_DURATION = Histogram(
    "radar_pipeline_stage_duration_seconds",
    "Duração de cada etapa do pipeline de análise",
    ["stage", "status"],
    registry=REGISTRY,
    buckets=(0.005, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
LLM_REQUESTS = Counter(
    "radar_llm_requests_total",
    "Chamadas a provedores de LLM",
    ["provider", "outcome"],
    registry=REGISTRY,
)
LLM_TOKENS = Counter(
    "radar_llm_tokens_total",
    "Tokens consumidos em provedores de LLM",
    ["provider", "direction"],
    registry=REGISTRY,
)
JOBS = Counter(
    "radar_jobs_total",
    "Jobs executados pelo worker",
    ["job", "status"],
    registry=REGISTRY,
)
