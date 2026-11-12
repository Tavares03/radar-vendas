"""Dados e configurações da empresa atual."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from radar.api.deps import DbDep, PrincipalDep, request_meta, require
from radar.api.errors import NotFound
from radar.api.schemas.core import TenantOut, TenantUpdate
from radar.auth.principal import Permission, Principal
from radar.db.models import Tenant
from radar.services.audit import AuditAction, record_audit

router = APIRouter(prefix="/tenant", tags=["empresa"])

AdminDep = Annotated[Principal, Depends(require(Permission.SETTINGS_MANAGE))]


def _tenant(db: DbDep, principal: Principal) -> Tenant:
    tenant = db.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Empresa não encontrada.")
    return tenant


@router.get("", response_model=TenantOut, summary="Empresa atual")
def get_tenant(db: DbDep, principal: PrincipalDep) -> TenantOut:
    return TenantOut.model_validate(_tenant(db, principal))


@router.patch("", response_model=TenantOut, summary="Alterar dados e configurações da empresa")
def update_tenant(
    body: TenantUpdate, request: Request, db: DbDep, principal: AdminDep
) -> TenantOut:
    tenant = _tenant(db, principal)
    changed: list[str] = []
    if body.name is not None:
        tenant.name = body.name.strip()
        changed.append("name")
    if body.default_playbook is not None:
        tenant.default_playbook = body.default_playbook
        changed.append("default_playbook")
    if body.settings is not None:
        tenant.set_settings(body.settings)
        changed.append("settings")
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.SETTINGS_UPDATED,
        principal=principal,
        resource_type="tenant",
        resource_id=tenant.id,
        details={"campos": changed},
        **request_meta(request),
    )
    db.commit()
    return TenantOut.model_validate(tenant)
