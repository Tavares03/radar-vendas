"""Cadastro de vendedores."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from radar.api.deps import DbDep, PrincipalDep, request_meta, require
from radar.api.errors import Conflict, NotFound
from radar.api.schemas.core import SellerCreate, SellerOut, SellerUpdate
from radar.auth.principal import Permission, Principal
from radar.db.models import Seller
from radar.services.audit import AuditAction, record_audit

router = APIRouter(prefix="/sellers", tags=["vendedores"])

ManagerDep = Annotated[Principal, Depends(require(Permission.SELLERS_MANAGE))]


def _clean_aliases(aliases: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for alias in aliases:
        cleaned = alias.strip()
        if cleaned:
            seen.setdefault(cleaned.lower(), cleaned)
    return list(seen.values())


def _name_taken(db: DbDep, name: str, ignore_id: uuid.UUID | None = None) -> bool:
    query = select(Seller.id).where(Seller.display_name == name)
    if ignore_id is not None:
        query = query.where(Seller.id != ignore_id)
    return db.execute(query).first() is not None


@router.get("", response_model=list[SellerOut], summary="Listar vendedores")
def list_sellers(db: DbDep, principal: PrincipalDep) -> list[SellerOut]:
    query = select(Seller).order_by(Seller.display_name)
    if principal.is_seller_restricted:
        # O vendedor só enxerga o próprio cadastro.
        query = query.where(Seller.id == principal.only_seller_id)
    return [SellerOut.model_validate(row) for row in db.scalars(query).all()]


@router.post("", response_model=SellerOut, status_code=201, summary="Criar vendedor")
def create(body: SellerCreate, request: Request, db: DbDep, principal: ManagerDep) -> SellerOut:
    name = body.display_name.strip()
    if _name_taken(db, name):
        raise Conflict("Já existe um vendedor com este nome.")
    seller = Seller(
        tenant_id=principal.tenant_id, display_name=name, aliases=_clean_aliases(body.aliases)
    )
    db.add(seller)
    db.flush()
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.SELLER_CREATED,
        principal=principal,
        resource_type="seller",
        resource_id=seller.id,
        **request_meta(request),
    )
    db.commit()
    return SellerOut.model_validate(seller)


@router.patch("/{seller_id}", response_model=SellerOut, summary="Alterar vendedor")
def update(
    seller_id: uuid.UUID, body: SellerUpdate, request: Request, db: DbDep, principal: ManagerDep
) -> SellerOut:
    seller = db.get(Seller, seller_id)
    if seller is None:
        raise NotFound("Vendedor não encontrado.")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("display_name"):
        name = changes["display_name"].strip()
        if _name_taken(db, name, ignore_id=seller.id):
            raise Conflict("Já existe um vendedor com este nome.")
        seller.display_name = name
    if changes.get("aliases") is not None:
        seller.aliases = _clean_aliases(changes["aliases"])
    if changes.get("is_active") is not None:
        seller.is_active = changes["is_active"]
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.SELLER_UPDATED,
        principal=principal,
        resource_type="seller",
        resource_id=seller.id,
        details={"campos": sorted(changes)},
        **request_meta(request),
    )
    db.commit()
    return SellerOut.model_validate(seller)


@router.delete("/{seller_id}", status_code=204, summary="Excluir vendedor")
def delete(seller_id: uuid.UUID, request: Request, db: DbDep, principal: ManagerDep) -> Response:
    """As conversas do vendedor são mantidas, sem vínculo."""
    seller = db.get(Seller, seller_id)
    if seller is None:
        raise NotFound("Vendedor não encontrado.")
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.SELLER_DELETED,
        principal=principal,
        resource_type="seller",
        resource_id=seller.id,
        details={"display_name": seller.display_name},
        **request_meta(request),
    )
    db.delete(seller)
    db.commit()
    return Response(status_code=204)
