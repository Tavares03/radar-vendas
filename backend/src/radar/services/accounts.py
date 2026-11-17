"""Empresas e usuários: criação, autenticação e primeiro acesso."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    burn_time,
    hash_password,
    needs_rehash,
    verify_password,
)
from radar.config import Settings, get_settings
from radar.db.models import Seller, Tenant, User
from radar.logs import get_logger
from radar.taxonomy import Role
from radar.tenant_settings import TenantSettings
from radar.textutil import plural

log = get_logger(__name__)


class AccountError(ValueError):
    """Regra de negócio violada ao criar ou alterar contas."""


def _check_password(password: str, min_length: int) -> None:
    if len(password) < max(1, min_length):
        raise AccountError(
            f"A senha precisa ter pelo menos {plural(max(1, min_length), 'caractere', 'caracteres')}."
        )


def slugify(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug[:60] or "empresa"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_tenant(
    db: Session,
    name: str,
    *,
    default_playbook: str = "generico",
    settings: TenantSettings | None = None,
) -> Tenant:
    base = slugify(name)
    slug = base
    suffix = 2
    while db.scalar(select(func.count()).select_from(Tenant).where(Tenant.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    tenant = Tenant(name=name.strip(), slug=slug, default_playbook=default_playbook)
    if settings is None:
        installation = get_settings()
        settings = TenantSettings(
            retention_raw_days=installation.default_retention_raw_days,
            retention_media_days=installation.default_retention_media_days,
        )
    tenant.set_settings(settings)
    db.add(tenant)
    db.flush()
    return tenant


def create_user(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    email: str,
    name: str,
    role: Role,
    password: str,
    seller_id: uuid.UUID | None = None,
    min_length: int = MIN_PASSWORD_LENGTH,
) -> User:
    """Cria um usuário. ``min_length`` só é relaxado para as contas da demonstração."""
    email = normalize_email(email)
    _check_password(password, min_length)
    exists = db.execute(
        select(User.id).where(User.email == email).execution_options(skip_tenant_filter=True)
    ).first()
    if exists is not None:
        raise AccountError("Já existe um usuário com este e-mail.")
    if seller_id is not None:
        seller = db.scalar(
            select(Seller).where(Seller.id == seller_id, Seller.tenant_id == tenant_id)
        )
        if seller is None:
            raise AccountError("Vendedor não encontrado nesta empresa.")
    user = User(
        tenant_id=tenant_id,
        email=email,
        name=name.strip(),
        role=role,
        password_hash=hash_password(password),
        seller_id=seller_id,
    )
    db.add(user)
    db.flush()
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Confere e-mail e senha. Gasta o mesmo tempo quando o e-mail não existe."""
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        burn_time()
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    return user


def set_password(user: User, new_password: str, *, min_length: int = MIN_PASSWORD_LENGTH) -> None:
    _check_password(new_password, min_length)
    user.password_hash = hash_password(new_password)
    # Derruba todas as sessões emitidas até aqui.
    user.session_version = (user.session_version or 0) + 1


def count_active_admins(db: Session, tenant_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.tenant_id == tenant_id, User.role == Role.ADMIN, User.is_active.is_(True))
        )
        or 0
    )


def bootstrap_from_settings(db: Session, settings: Settings) -> User | None:
    """Cria a empresa e o admin iniciais a partir do ``.env`` quando o banco está vazio."""
    email = normalize_email(settings.bootstrap_admin_email)
    password = (
        settings.bootstrap_admin_password.get_secret_value()
        if settings.bootstrap_admin_password
        else ""
    )
    if not email or not password:
        return None
    if db.scalar(select(func.count()).select_from(User)):
        return None
    tenant = create_tenant(db, settings.bootstrap_tenant_name or "Minha Empresa")
    user = create_user(
        db,
        tenant_id=tenant.id,
        email=email,
        name="Administrador",
        role=Role.ADMIN,
        password=password,
    )
    db.commit()
    log.info("bootstrap_admin_criado", tenant=tenant.slug, email=email)
    return user
