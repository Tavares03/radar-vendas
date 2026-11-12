"""Envio de conversas exportadas do WhatsApp (um arquivo ou vários)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import ColumnElement

from radar.api.deps import DbDep, SettingsDep, request_meta, require
from radar.api.errors import BadRequest, Forbidden, NotFound
from radar.api.paging import paginate
from radar.api.schemas.common import Page, Pagination, pagination
from radar.api.schemas.conversations import ImportOut
from radar.auth.principal import Permission, Principal
from radar.db.models import Import, Seller
from radar.services.audit import AuditAction, record_audit
from radar.services.ingestion import (
    USER_ERRORS,
    UploadTooLarge,
    find_duplicate_import,
    relative_to_data,
    store_upload,
    validate_export,
)
from radar.taxonomy import ImportSource, ImportStatus
from radar.worker.jobs import enqueue_import

router = APIRouter(prefix="/imports", tags=["importação"])

WriterDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_WRITE))]
ReaderDep = Annotated[Principal, Depends(require(Permission.CONVERSATIONS_READ))]

MAX_FILES_PER_REQUEST = 50
_ALLOWED_SUFFIXES = (".zip", ".txt")


def _safe_display_name(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:255] or "arquivo"


@router.post(
    "",
    response_model=list[ImportOut],
    status_code=201,
    summary="Enviar conversas exportadas",
)
def upload(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    principal: WriterDep,
    files: Annotated[
        list[UploadFile],
        File(description="Arquivos .zip ou .txt gerados por “Exportar conversa” no WhatsApp."),
    ],
    seller_id: Annotated[
        uuid.UUID | None, Form(description="Vendedor dono das conversas (opcional).")
    ] = None,
    seller_name: Annotated[
        str | None,
        Form(max_length=200, description="Nome do vendedor como aparece no arquivo (opcional)."),
    ] = None,
    playbook: Annotated[
        str | None, Form(max_length=80, description="Playbook a aplicar (padrão: o da empresa).")
    ] = None,
) -> list[ImportOut]:
    """Cada arquivo vira uma importação, processada em segundo plano.

    A resposta traz um item por arquivo, na mesma ordem. Um arquivo inválido não impede os
    outros: ele volta com `status: "falhou"` e o motivo em `error`. Reenviar um arquivo já
    importado devolve a importação original com `duplicate: true`.
    """
    if not files:
        raise BadRequest("Envie pelo menos um arquivo.")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise BadRequest(f"Envie no máximo {MAX_FILES_PER_REQUEST} arquivos por vez.")

    if principal.is_seller_restricted:
        # O vendedor só importa as próprias conversas.
        if principal.only_seller_id is None:
            raise Forbidden("Seu usuário ainda não está vinculado a um vendedor.")
        seller_id = principal.only_seller_id
    if seller_id is not None and db.get(Seller, seller_id) is None:
        raise NotFound("Vendedor não encontrado.")

    options = {
        "seller_id": str(seller_id) if seller_id else None,
        "seller_name": (seller_name or "").strip() or None,
        "playbook": (playbook or "").strip() or None,
    }
    meta = request_meta(request)
    results: list[tuple[Import, bool]] = []
    to_enqueue: list[uuid.UUID] = []

    for file in files:
        name = _safe_display_name(file.filename)
        record = Import(
            tenant_id=principal.tenant_id,
            source=ImportSource.WHATSAPP_EXPORT,
            filename=name,
            created_by_user_id=principal.user_id,
            created_by_label=principal.label,
            options=options,
        )
        if not name.lower().endswith(_ALLOWED_SUFFIXES):
            record.status = ImportStatus.FALHOU
            record.error = (
                "Tipo de arquivo não aceito. Envie o .zip ou o .txt exportado do WhatsApp."
            )
            db.add(record)
            results.append((record, False))
            continue
        try:
            stored = store_upload(file.file, tenant_id=principal.tenant_id, settings=settings)
        except UploadTooLarge as exc:
            record.status, record.error = ImportStatus.FALHOU, str(exc)
            db.add(record)
            results.append((record, False))
            continue

        record.file_sha256, record.size_bytes = stored.sha256, stored.size
        duplicate = find_duplicate_import(db, stored.sha256)
        if duplicate is not None:
            stored.path.unlink(missing_ok=True)
            results.append((duplicate, True))
            continue
        try:
            validate_export(stored.path, original_name=name, settings=settings)
        except USER_ERRORS as exc:
            stored.path.unlink(missing_ok=True)
            record.status, record.error = ImportStatus.FALHOU, str(exc)
            db.add(record)
            results.append((record, False))
            continue

        record.stored_path = relative_to_data(stored.path, settings)
        db.add(record)
        db.flush()
        record_audit(
            db,
            tenant_id=principal.tenant_id,
            action=AuditAction.IMPORT_CREATED,
            principal=principal,
            resource_type="import",
            resource_id=record.id,
            details={"bytes": stored.size},
            **meta,
        )
        results.append((record, False))
        to_enqueue.append(record.id)

    db.commit()
    for import_id in to_enqueue:
        enqueue_import(import_id, principal.tenant_id)

    output: list[ImportOut] = []
    for record, is_duplicate in results:
        db.refresh(record)
        item = ImportOut.model_validate(record)
        item.duplicate = is_duplicate
        output.append(item)
    return output


@router.get("", response_model=Page[ImportOut], summary="Listar importações")
def list_imports(
    db: DbDep,
    principal: ReaderDep,
    page: Annotated[Pagination, Depends(pagination)],
    status: ImportStatus | None = None,
) -> Page[ImportOut]:
    filters: list[ColumnElement[bool]] = []
    if principal.is_seller_restricted:
        filters.append(Import.created_by_user_id == principal.user_id)
    if status is not None:
        filters.append(Import.status == status)
    rows, total = paginate(
        db, Import, filters=filters, order_by=[Import.created_at.desc()], page=page
    )
    return Page[ImportOut](
        items=[ImportOut.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{import_id}", response_model=ImportOut, summary="Consultar uma importação")
def get_import(import_id: uuid.UUID, db: DbDep, principal: ReaderDep) -> ImportOut:
    record = db.get(Import, import_id)
    if record is None or (
        principal.is_seller_restricted and record.created_by_user_id != principal.user_id
    ):
        raise NotFound("Importação não encontrada.")
    return ImportOut.model_validate(record)
