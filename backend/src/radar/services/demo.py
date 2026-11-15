"""Empresa de demonstração com as conversas sintéticas de ``data/samples/demo``.

Uma equipe fictícia de consórcio (cinco vendedores, oito semanas de conversas), gerada pelo
``radar-synth demo``. Tudo é sintético. Os usuários criados (admin, gestor e vendedor
``@demo.radar``) existem só para experimentar o painel; não use isso numa instalação exposta.

Os exports foram gerados em torno de uma data-âncora fixa. Na carga, as datas são deslocadas em
semanas inteiras para que a âncora seja a semana atual: quem abre a demonstração vê as últimas
oito semanas, em qualquer dia em que a carregue.
"""

from __future__ import annotations

import io
import json
import re
import secrets
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from radar.config import Settings
from radar.db.models import Conversation, Import, Seller, Tenant, User
from radar.db.session import session_scope
from radar.logs import get_logger
from radar.services.accounts import create_tenant, create_user
from radar.services.ingestion import process_import, relative_to_data, store_upload
from radar.taxonomy import ImportSource, ImportStatus, Role

log = get_logger(__name__)

DEMO_SLUG = "demonstracao"
#: O login de vendedor entra como esta pessoa da equipe (e só vê as conversas dela).
DEMO_SELLER = "Vera Nunes"
DEMO_USERS = (
    ("admin@demo.radar", "Ana Admin", Role.ADMIN),
    ("gestor@demo.radar", "Gustavo Gestor", Role.GESTOR),
    ("vendedor@demo.radar", DEMO_SELLER, Role.VENDEDOR),
)

#: Carimbo de data do export do Android em português: ``31/12/2026 08:15 - ``.
_STAMP = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?= \d{2}:\d{2} - )", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class DemoResult:
    created: bool
    conversations: int


def samples_dir(settings: Settings) -> Path:
    base = settings.samples_dir or Path(__file__).resolve().parents[4] / "data" / "samples"
    return base / "demo"


def shift_days(anchor: date, today: date) -> int:
    """Quantos dias (múltiplo de 7, para manter o dia da semana) levam a âncora à semana atual."""
    return 7 * ((today - anchor).days // 7)


def shift_export(data: bytes, days: int) -> bytes:
    """O mesmo export com todas as datas das mensagens ``days`` dias depois."""
    if days == 0:
        return data
    delta = timedelta(days=days)

    def move(match: re.Match[str]) -> str:
        day, month, year = (int(g) for g in match.groups())
        return (date(year, month, day) + delta).strftime("%d/%m/%Y")

    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            content = source.read(info)
            if info.filename.lower().endswith(".txt"):
                content = _STAMP.sub(move, content.decode("utf-8")).encode("utf-8")
            target.writestr(info.filename, content)
    return buffer.getvalue()


def _manifest(folder: Path) -> dict[str, Any]:
    path = folder / "demo.json"
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def seed_demo(
    settings: Settings, *, password: str, today: date | None = None, background: bool = False
) -> DemoResult:
    """Cria a empresa de demonstração. Com ``background``, a análise vai para a fila de jobs."""
    folder = samples_dir(settings)
    manifest = _manifest(folder)
    playbook = str(manifest.get("playbook") or "consorcio")
    team = [str(name) for name in manifest.get("equipe") or []]
    anchor_text = str(manifest.get("ancora") or "")
    today = today or datetime.now().date()
    days = shift_days(date.fromisoformat(anchor_text), today) if anchor_text else 0

    with session_scope() as db:
        existing = db.scalar(select(Tenant).where(Tenant.slug == DEMO_SLUG))
        if existing is not None:
            return DemoResult(created=False, conversations=0)
        tenant = create_tenant(db, "Demonstração", default_playbook=playbook)
        company = str(manifest.get("empresa") or "")
        if company:
            # O endereço (slug) continua "demonstracao"; o nome mostra a empresa fictícia.
            tenant.name = f"{company} (demonstração)"
        sellers = {
            name: Seller(tenant_id=tenant.id, display_name=name, aliases=[]) for name in team
        }
        db.add_all(sellers.values())
        db.flush()
        for email, name, role in DEMO_USERS:
            user = create_user(
                db, tenant_id=tenant.id, email=email, name=name, role=role, password=password
            )
            if role is Role.VENDEDOR and name in sellers:
                user.seller_id = sellers[name].id
        tenant_id = tenant.id

    import_ids: list[uuid.UUID] = []
    for path in sorted(folder.glob("*.zip")):
        with session_scope(tenant_id) as db:
            stored = store_upload(
                io.BytesIO(shift_export(path.read_bytes(), days)),
                tenant_id=tenant_id,
                settings=settings,
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
                options={"playbook": playbook},
            )
            db.add(record)
            db.flush()
            import_ids.append(record.id)

    if background:
        from radar.worker.jobs import enqueue_import

        for import_id in import_ids:
            enqueue_import(import_id, tenant_id)
        return DemoResult(created=True, conversations=len(import_ids))

    for import_id in import_ids:
        process_import(import_id, tenant_id)
    with session_scope(tenant_id) as db:
        if not team:
            # Amostras sem equipe cadastrada: o login de vendedor vê o primeiro vendedor importado.
            seller_id = db.scalar(
                select(Conversation.seller_id).where(Conversation.seller_id.is_not(None))
            )
            login = db.scalar(select(User).where(User.email == "vendedor@demo.radar"))
            if login is not None and seller_id is not None:
                login.seller_id = seller_id
        total = db.scalar(select(func.count()).select_from(Conversation)) or 0
        return DemoResult(created=True, conversations=total)


def seed_demo_on_first_boot(settings: Settings) -> str | None:
    """Carrega a demonstração na primeira subida (``RADAR_SEED_DEMO=true`` e banco sem usuários).

    Devolve a senha dos usuários ``@demo.radar`` quando criou a demonstração. Sem
    ``RADAR_DEMO_PASSWORD``, a senha é sorteada e aparece uma única vez no log da API.
    """
    if not settings.seed_demo or settings.environment == "prod":
        return None
    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(User)):
            return None
    if not any(samples_dir(settings).glob("*.zip")):
        log.warning("demonstracao_sem_amostras", pasta=str(samples_dir(settings)))
        return None
    if settings.queue_mode == "rq":
        # Sem fila, a demonstração ficaria criada e nunca analisada; melhor tentar na próxima subida.
        from radar.worker.queue import get_redis

        get_redis().ping()
    configured = settings.demo_password.get_secret_value() if settings.demo_password else ""
    password = configured or secrets.token_urlsafe(12)
    result = seed_demo(settings, password=password, background=True)
    if not result.created:
        return None
    log.warning(
        "demonstracao_criada",
        conversas=result.conversations,
        usuarios=", ".join(email for email, _name, _role in DEMO_USERS),
        senha=password if not configured else "a de RADAR_DEMO_PASSWORD",
        aviso="dados sintéticos; desligue com RADAR_SEED_DEMO=false",
    )
    return password
