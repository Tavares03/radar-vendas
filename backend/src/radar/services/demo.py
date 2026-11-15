"""Empresa de demonstração com as conversas sintéticas de ``data/samples/synthetic``.

Tudo é sintético. Os usuários criados (admin, gestor e vendedor ``@demo.radar``) existem só para
experimentar o painel; não use isso numa instalação exposta.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from radar.config import Settings
from radar.db.models import Conversation, Import, Tenant
from radar.db.session import session_scope
from radar.services.accounts import create_tenant, create_user
from radar.services.ingestion import process_import, relative_to_data, store_upload
from radar.taxonomy import ImportSource, ImportStatus, Role

DEMO_SLUG = "demonstracao"
DEMO_USERS = (
    ("admin@demo.radar", "Ana Admin", Role.ADMIN),
    ("gestor@demo.radar", "Gustavo Gestor", Role.GESTOR),
    ("vendedor@demo.radar", "Vera Vendedora", Role.VENDEDOR),
)


@dataclass(frozen=True, slots=True)
class DemoResult:
    created: bool
    conversations: int


def samples_dir(settings: Settings) -> Path:
    base = settings.samples_dir or Path(__file__).resolve().parents[4] / "data" / "samples"
    return base / "synthetic"


def seed_demo(settings: Settings, *, password: str) -> DemoResult:
    with session_scope() as db:
        existing = db.scalar(select(Tenant).where(Tenant.slug == DEMO_SLUG))
        if existing is not None:
            return DemoResult(created=False, conversations=0)
        tenant = create_tenant(db, "Demonstração", default_playbook="consorcio")
        for email, name, role in DEMO_USERS:
            create_user(
                db, tenant_id=tenant.id, email=email, name=name, role=role, password=password
            )
        tenant_id = tenant.id

    import_ids: list[uuid.UUID] = []
    for path in sorted(samples_dir(settings).glob("*.zip")):
        sector = path.stem.split("-")[1] if path.stem.count("-") >= 2 else "generico"
        with session_scope(tenant_id) as db:
            stored = store_upload(
                io.BytesIO(path.read_bytes()), tenant_id=tenant_id, settings=settings
            )
            record = Import(
                tenant_id=tenant_id,
                source=ImportSource.WHATSAPP_EXPORT,
                status=ImportStatus.PENDENTE,
                filename=path.name,
                file_sha256=stored.sha256,
                size_bytes=stored.size,
                stored_path=relative_to_data(stored.path, settings),
                created_by_label="demonstração",
                options={"playbook": sector},
            )
            db.add(record)
            db.flush()
            import_ids.append(record.id)
    for import_id in import_ids:
        process_import(import_id, tenant_id)

    with session_scope(tenant_id) as db:
        conversations = list(db.scalars(select(Conversation)))
        # A vendedora da demonstração vê as conversas do primeiro vendedor importado.
        seller_id = next((c.seller_id for c in conversations if c.seller_id), None)
        if seller_id is not None:
            from radar.db.models import User

            user = db.scalar(select(User).where(User.email == "vendedor@demo.radar"))
            if user is not None:
                user.seller_id = seller_id
        return DemoResult(created=True, conversations=len(conversations))
