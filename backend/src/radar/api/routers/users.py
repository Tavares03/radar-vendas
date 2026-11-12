"""Gestão de usuários da empresa (somente admin)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select

from radar.api.deps import DbDep, request_meta, require
from radar.api.errors import BadRequest, Conflict, NotFound
from radar.api.schemas.common import Page, Pagination, pagination
from radar.api.schemas.core import UserCreate, UserOut, UserUpdate
from radar.auth.principal import Permission, Principal
from radar.db.models import Seller, User
from radar.services.accounts import AccountError, count_active_admins, create_user, set_password
from radar.services.audit import AuditAction, record_audit
from radar.taxonomy import Role

router = APIRouter(prefix="/users", tags=["usuários"])

AdminDep = Annotated[Principal, Depends(require(Permission.USERS_MANAGE))]


def _get_user(db: DbDep, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("Usuário não encontrado.")
    return user


@router.get("", response_model=Page[UserOut], summary="Listar usuários")
def list_users(
    db: DbDep, _principal: AdminDep, page: Annotated[Pagination, Depends(pagination)]
) -> Page[UserOut]:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    rows = db.scalars(select(User).order_by(User.name).limit(page.limit).offset(page.offset)).all()
    return Page(
        items=[UserOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=UserOut, status_code=201, summary="Criar usuário")
def create(body: UserCreate, request: Request, db: DbDep, principal: AdminDep) -> UserOut:
    try:
        user = create_user(
            db,
            tenant_id=principal.tenant_id,
            email=body.email,
            name=body.name,
            role=body.role,
            password=body.password,
            seller_id=body.seller_id,
        )
    except AccountError as exc:
        db.rollback()
        raise Conflict(str(exc)) from exc
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.USER_CREATED,
        principal=principal,
        resource_type="user",
        resource_id=user.id,
        details={"role": user.role.value},
        **request_meta(request),
    )
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut, summary="Alterar usuário")
def update(
    user_id: uuid.UUID, body: UserUpdate, request: Request, db: DbDep, principal: AdminDep
) -> UserOut:
    user = _get_user(db, user_id)
    changes = body.model_dump(exclude_unset=True)

    demoting = "role" in changes and changes["role"] != Role.ADMIN and user.role == Role.ADMIN
    deactivating = changes.get("is_active") is False and user.is_active
    if (
        (demoting or deactivating)
        and user.role == Role.ADMIN
        and count_active_admins(db, principal.tenant_id) <= 1
    ):
        raise BadRequest("A empresa precisa de pelo menos um administrador ativo.")

    new_seller_id = changes.get("seller_id")
    if new_seller_id is not None and db.get(Seller, new_seller_id) is None:
        raise NotFound("Vendedor não encontrado.")
    if "name" in changes and changes["name"] is not None:
        user.name = changes["name"].strip()
    if "role" in changes and changes["role"] is not None:
        user.role = changes["role"]
    if "seller_id" in changes:
        user.seller_id = changes["seller_id"]
    if "is_active" in changes and changes["is_active"] is not None:
        user.is_active = changes["is_active"]
    if changes.get("password"):
        try:
            set_password(user, changes["password"])
        except AccountError as exc:
            raise BadRequest(str(exc)) from exc

    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.USER_UPDATED,
        principal=principal,
        resource_type="user",
        resource_id=user.id,
        details={"campos": sorted(k for k in changes if k != "password")},
        **request_meta(request),
    )
    db.commit()
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204, summary="Excluir usuário")
def delete(user_id: uuid.UUID, request: Request, db: DbDep, principal: AdminDep) -> Response:
    user = _get_user(db, user_id)
    if user.id == principal.user_id:
        raise BadRequest("Você não pode excluir a própria conta.")
    if user.role == Role.ADMIN and count_active_admins(db, principal.tenant_id) <= 1:
        raise BadRequest("A empresa precisa de pelo menos um administrador ativo.")
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.USER_DELETED,
        principal=principal,
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email},
        **request_meta(request),
    )
    db.delete(user)
    db.commit()
    return Response(status_code=204)
