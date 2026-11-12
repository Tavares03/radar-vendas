"""Login, logout, sessão atual e troca de senha."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.api.deps import DbDep, PrincipalDep, SettingsDep, request_meta
from radar.api.errors import BadRequest, Conflict, Forbidden, NotFound, Unauthorized
from radar.api.rate_limit import client_ip, enforce
from radar.api.schemas.common import Message
from radar.api.schemas.core import (
    ChangePasswordIn,
    LoginIn,
    LoginOut,
    MeOut,
    SignupIn,
    TenantOut,
)
from radar.auth.jwt import create_session_token
from radar.auth.passwords import verify_password
from radar.auth.principal import ROLE_PERMISSIONS
from radar.config import Settings
from radar.db.models import Tenant, User
from radar.db.session import scope_session
from radar.services.accounts import (
    AccountError,
    authenticate,
    create_tenant,
    create_user,
    normalize_email,
    set_password,
)
from radar.services.audit import AuditAction, record_audit
from radar.taxonomy import Role

router = APIRouter(prefix="/auth", tags=["autenticação"])


def _me(db: Session, user: User) -> MeOut:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise NotFound("Empresa não encontrada.")
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        seller_id=user.seller_id,
        permissions=sorted(p.value for p in ROLE_PERMISSIONS[user.role]),
        tenant=TenantOut.model_validate(tenant),
    )


def _start_session(response: Response, settings: Settings, db: Session, user: User) -> LoginOut:
    token, expires_at = create_session_token(
        user.id, user.tenant_id, session_version=user.session_version
    )
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.jwt_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return LoginOut(access_token=token, expires_at=expires_at, user=_me(db, user))


@router.post("/login", response_model=LoginOut, summary="Entrar com e-mail e senha")
def login(
    body: LoginIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> LoginOut:
    email = normalize_email(body.email)
    enforce(f"login-ip:{client_ip(request)}", settings.login_rate_limit_per_minute * 3)
    enforce(f"login-email:{email}", settings.login_rate_limit_per_minute)

    user = authenticate(db, email, body.password)
    if user is None:
        known = db.scalar(select(User).where(User.email == email))
        if known is not None:
            record_audit(
                db,
                tenant_id=known.tenant_id,
                action=AuditAction.LOGIN_FAILED,
                actor_label=email,
                resource_type="user",
                resource_id=known.id,
                **request_meta(request),
            )
            db.commit()
        raise Unauthorized("E-mail ou senha incorretos.")

    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise Unauthorized("E-mail ou senha incorretos.")

    record_audit(
        db,
        tenant_id=user.tenant_id,
        action=AuditAction.LOGIN,
        actor_label=user.email,
        resource_type="user",
        resource_id=user.id,
        **request_meta(request),
    )
    db.commit()
    return _start_session(response, settings, db, user)


@router.post("/signup", response_model=LoginOut, status_code=201, summary="Criar empresa e admin")
def signup(
    body: SignupIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> LoginOut:
    """Disponível só quando ``RADAR_ALLOW_SIGNUP=true``."""
    if not settings.allow_signup:
        raise Forbidden("O cadastro aberto está desativado nesta instalação.")
    enforce(f"signup-ip:{client_ip(request)}", settings.login_rate_limit_per_minute)
    try:
        tenant = create_tenant(db, body.company_name)
        user = create_user(
            db,
            tenant_id=tenant.id,
            email=body.email,
            name=body.name,
            role=Role.ADMIN,
            password=body.password,
        )
    except AccountError as exc:
        db.rollback()
        raise Conflict(str(exc)) from exc
    record_audit(
        db,
        tenant_id=tenant.id,
        action=AuditAction.USER_CREATED,
        actor_label=user.email,
        resource_type="user",
        resource_id=user.id,
        details={"origem": "signup"},
        **request_meta(request),
    )
    db.commit()
    return _start_session(response, settings, db, user)


@router.post("/logout", response_model=Message, summary="Sair")
def logout(
    request: Request,
    response: Response,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> Message:
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.LOGOUT,
        principal=principal,
        **request_meta(request),
    )
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    return Message(message="Sessão encerrada.")


@router.get("/me", response_model=MeOut, summary="Usuário e empresa da sessão atual")
def me(db: DbDep, principal: PrincipalDep) -> MeOut:
    if principal.user_id is None:
        raise BadRequest("Tokens de API não têm perfil de usuário.")
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("Usuário não encontrado.")
    return _me(db, user)


@router.post("/change-password", response_model=LoginOut, summary="Trocar a própria senha")
def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> LoginOut:
    """Troca a senha, encerra as outras sessões e devolve uma sessão nova."""
    if principal.user_id is None:
        raise BadRequest("Tokens de API não têm senha.")
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("Usuário não encontrado.")
    if not verify_password(body.current_password, user.password_hash):
        raise Unauthorized("Senha atual incorreta.")
    try:
        set_password(user, body.new_password)
    except AccountError as exc:
        raise BadRequest(str(exc)) from exc
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.PASSWORD_CHANGED,
        principal=principal,
        resource_type="user",
        resource_id=user.id,
        **request_meta(request),
    )
    db.commit()
    scope_session(db, user.tenant_id)
    return _start_session(response, settings, db, user)
