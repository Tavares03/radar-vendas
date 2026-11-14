"""Playbooks: os que vêm com o Radar e os escritos pela empresa (YAML, sem programar)."""

from __future__ import annotations

from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from radar.api.deps import DbDep, request_meta, require
from radar.api.errors import BadRequest, NotFound, Unprocessable
from radar.api.schemas.analysis import (
    PlaybookDetail,
    PlaybookIn,
    PlaybookSummary,
    PlaybookTestIn,
    PlaybookTestOut,
    RuleHitOut,
)
from radar.auth.principal import Permission, Principal
from radar.db.models import TenantPlaybook
from radar.playbooks import (
    Playbook,
    PlaybookError,
    RuleEngine,
    available_playbooks,
    parse_playbook,
    read_builtin,
)
from radar.services.analysis import playbook_resolver
from radar.services.audit import AuditAction, record_audit
from radar.taxonomy import SenderRole

router = APIRouter(prefix="/playbooks", tags=["playbooks"])

ReaderDep = Annotated[Principal, Depends(require(Permission.PLAYBOOKS_READ))]
WriterDep = Annotated[Principal, Depends(require(Permission.PLAYBOOKS_WRITE))]


def _custom(db: DbDep, slug: str) -> TenantPlaybook | None:
    return db.scalar(select(TenantPlaybook).where(TenantPlaybook.slug == slug))


def _parse(db: DbDep, text: str) -> Playbook:
    try:
        return parse_playbook(text, resolver=playbook_resolver(db))
    except PlaybookError as exc:
        raise Unprocessable(str(exc), code="invalid_playbook") from exc


@router.get("", response_model=list[PlaybookSummary], summary="Listar playbooks")
def list_playbooks(db: DbDep, principal: ReaderDep) -> list[PlaybookSummary]:
    custom = {
        row.slug: row
        for row in db.scalars(select(TenantPlaybook).where(TenantPlaybook.is_active.is_(True)))
    }
    items = []
    for slug in available_playbooks():
        if slug in custom:
            continue
        data: dict[str, Any] = yaml.safe_load(read_builtin(slug) or "") or {}
        items.append(
            PlaybookSummary(
                slug=slug,
                name=str(data.get("nome", slug)),
                origin="padrao",
                version=int(data.get("versao", 1)),
                description=str(data.get("descricao", "")).strip(),
            )
        )
    for slug, row in sorted(custom.items()):
        items.append(
            PlaybookSummary(slug=slug, name=row.name, origin="empresa", version=row.version)
        )
    return sorted(items, key=lambda p: (p.origin != "empresa", p.slug))


@router.get("/{slug}", response_model=PlaybookDetail, summary="Ver um playbook")
def get_playbook(slug: str, db: DbDep, principal: ReaderDep) -> PlaybookDetail:
    row = _custom(db, slug)
    text = row.content if row is not None else read_builtin(slug)
    if text is None:
        raise NotFound("Playbook não encontrado.")
    playbook = _parse(db, text)
    return PlaybookDetail(
        slug=slug,
        name=playbook.nome,
        origin="empresa" if row is not None else "padrao",
        version=row.version if row is not None else playbook.versao,
        description=playbook.descricao,
        yaml=text,
        playbook=playbook.model_dump(mode="json"),
    )


@router.put(
    "/{slug}", response_model=PlaybookDetail, summary="Criar ou atualizar um playbook da empresa"
)
def save_playbook(
    slug: str, body: PlaybookIn, request: Request, db: DbDep, principal: WriterDep
) -> PlaybookDetail:
    """Valida o YAML (padrões, tipos, pesos da nota, herança) antes de salvar. Um playbook da
    empresa com o mesmo nome de um padrão (por exemplo ``consorcio``) passa a valer no lugar dele."""
    playbook = _parse(db, body.yaml)
    if playbook.id != slug:
        raise BadRequest(
            f"O id do YAML ('{playbook.id}') precisa ser igual ao endereço ('{slug}')."
        )
    row = _custom(db, slug)
    if row is None:
        row = TenantPlaybook(
            tenant_id=principal.tenant_id,
            slug=slug,
            name=playbook.nome,
            content=body.yaml,
            version=1,
        )
        db.add(row)
    else:
        row.name, row.content, row.version, row.is_active = (
            playbook.nome,
            body.yaml,
            row.version + 1,
            True,
        )
    row.updated_by_user_id = principal.user_id
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.PLAYBOOK_SAVED,
        principal=principal,
        resource_type="playbook",
        resource_id=slug,
        details={"versao": row.version, "regras": len(playbook.regras)},
        **request_meta(request),
    )
    db.commit()
    return PlaybookDetail(
        slug=slug,
        name=playbook.nome,
        origin="empresa",
        version=row.version,
        description=playbook.descricao,
        yaml=body.yaml,
        playbook=playbook.model_dump(mode="json"),
    )


@router.delete("/{slug}", status_code=204, summary="Excluir um playbook da empresa")
def delete_playbook(slug: str, request: Request, db: DbDep, principal: WriterDep) -> Response:
    row = _custom(db, slug)
    if row is None:
        if slug in available_playbooks():
            raise BadRequest(
                "Playbooks padrão não podem ser excluídos; crie um da empresa com o mesmo nome."
            )
        raise NotFound("Playbook não encontrado.")
    db.delete(row)
    record_audit(
        db,
        tenant_id=principal.tenant_id,
        action=AuditAction.PLAYBOOK_DELETED,
        principal=principal,
        resource_type="playbook",
        resource_id=slug,
        **request_meta(request),
    )
    db.commit()
    return Response(status_code=204)


@router.post("/{slug}/test", response_model=PlaybookTestOut, summary="Testar regras em mensagens")
def test_playbook(
    slug: str, body: PlaybookTestIn, db: DbDep, principal: ReaderDep
) -> PlaybookTestOut:
    """Aplica o playbook (ou um rascunho em ``yaml``) a mensagens de exemplo, sem salvar nada."""
    if body.yaml is not None:
        playbook = _parse(db, body.yaml)
    else:
        row = _custom(db, slug)
        text = row.content if row is not None else read_builtin(slug)
        if text is None:
            raise NotFound("Playbook não encontrado.")
        playbook = _parse(db, text)
    engine = RuleEngine(playbook)
    messages = [(SenderRole(m.sender), m.text) for m in body.messages]
    hits = [
        RuleHitOut(
            message_index=h.message_index,
            rule_id=h.rule_id,
            type=h.type,
            severity=h.severity.value if h.severity else None,
            evidence=h.evidence,
            explanation=h.explanation,
        )
        for h in engine.evaluate(messages)
    ]
    return PlaybookTestOut(hits=hits, disclosures=engine.disclosures(messages))
