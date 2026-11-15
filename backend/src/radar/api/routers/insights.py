"""Indicadores do painel: visão geral e desempenho por vendedor."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from radar.api.deps import DbDep, require
from radar.api.errors import NotFound
from radar.api.schemas.conversations import ConversationOut, SellerBrief
from radar.auth.principal import Permission, Principal
from radar.db.models import Seller
from radar.services.insights import overview, seller_performance

router = APIRouter(tags=["visão geral"])

AnalystDep = Annotated[Principal, Depends(require(Permission.ANALYTICS_READ))]


class WeekOut(BaseModel):
    week_start: date
    conversations: int
    average_score: float | None
    critical_alerts: int


class SellerSummaryOut(BaseModel):
    seller_id: uuid.UUID
    name: str
    conversations: int
    average_score: float | None
    open_alerts: int
    critical_alerts: int


class TypeCountOut(BaseModel):
    type: str
    label: str
    count: int


class OverviewOut(BaseModel):
    period_days: int
    #: Data da atividade mais recente da empresa: o período conta a partir dela.
    reference_date: date
    conversations_analyzed: int
    average_score: float | None
    open_alerts: dict[str, int]
    weekly: list[WeekOut]
    sellers: list[SellerSummaryOut]
    alert_types: list[TypeCountOut]


class ObjectionStatsOut(BaseModel):
    type: str
    label: str
    total: int
    bem: int
    parcial: int
    mal: int
    sem_resposta: int


class CriterionAverageOut(BaseModel):
    id: str
    label: str
    average_points: float
    maximum: int


class SellerPerformanceOut(BaseModel):
    seller: SellerBrief
    conversations: int
    average_score: float | None
    weekly: list[WeekOut]
    alerts_by_type: list[TypeCountOut]
    objections: list[ObjectionStatsOut]
    criteria: list[CriterionAverageOut]
    #: Pontos a melhorar mais repetidos nas análises (vêm do LLM).
    improvements: list[str]
    recent: list[ConversationOut]


@router.get("/overview", response_model=OverviewOut, summary="Visão geral da empresa")
def get_overview(
    db: DbDep,
    principal: AnalystDep,
    days: Annotated[int, Query(ge=7, le=365, description="Tamanho do período, em dias")] = 30,
) -> OverviewOut:
    return OverviewOut.model_validate(overview(db, days=days))


@router.get(
    "/sellers/{seller_id}/performance",
    response_model=SellerPerformanceOut,
    summary="Desempenho de um vendedor",
)
def get_seller_performance(
    seller_id: uuid.UUID, db: DbDep, principal: AnalystDep
) -> SellerPerformanceOut:
    seller = db.get(Seller, seller_id)
    if seller is None:
        raise NotFound("Vendedor não encontrado.")
    data = seller_performance(db, seller)
    data["recent"] = [ConversationOut.model_validate(c) for c in data["recent"]]
    return SellerPerformanceOut.model_validate(data)
