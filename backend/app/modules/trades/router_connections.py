"""Seção "Integrações": conexões com corretoras."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.credentials import credential_hint, delete_secret, store_secret
from app.core.deps import require_permission
from app.core.errors import AppError, Conflict, NotFound
from app.core.redaction import redact_text
from app.db import get_db
from app.integrations.base import AdapterError, InsufficientPermissions, InvalidCredentials, TemporaryError
from app.integrations.registry import ADAPTERS, build_adapter
from app.models import ConnectionStatus, ExchangeConnection, ExchangeProvider, SyncJob, User
from app.models.base import utcnow
from app.modules.trades.pnl.service import recalculate_user
from app.modules.trades.sync import CONNECTION_OWNER, enqueue_sync

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
PERM = "integrations:manage"
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")


class ConnectionSettings(BaseModel):
    extra_symbols: list[str] = Field(default_factory=list, max_length=200)
    history_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("extra_symbols")
    @classmethod
    def _symbols(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            s = s.strip().upper().replace("/", "")
            if s and not _SYMBOL_RE.match(s):
                raise ValueError(f"Par inválido: {s[:20]}")
            if s:
                out.append(s)
        return sorted(set(out))


class ConnectionIn(BaseModel):
    provider: str
    name: str = Field(min_length=1, max_length=80)
    credentials: dict[str, str]
    settings: ConnectionSettings = Field(default_factory=ConnectionSettings)


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    settings: ConnectionSettings | None = None


class CredentialsIn(BaseModel):
    credentials: dict[str, str]


def _validate_credential_fields(provider_key: str, creds: dict[str, str]) -> dict[str, str]:
    info = ADAPTERS[provider_key].info
    clean = {}
    for f in info.credential_fields:
        v = (creds.get(f.name) or "").strip()
        if not v or len(v) > 512 or any(c.isspace() for c in v):
            raise AppError(f"Informe um valor válido para '{f.label}'.")
        clean[f.name] = v
    return clean


def _hint(creds: dict[str, str]) -> str | None:
    key = creds.get("api_key")
    return f"…{key[-4:]}" if key else None


def _out(db: Session, c: ExchangeConnection) -> dict:
    hint, updated = credential_hint(db, CONNECTION_OWNER, c.id)
    last_job = db.scalar(select(SyncJob).where(SyncJob.connection_id == c.id).order_by(SyncJob.created_at.desc()).limit(1))
    return {
        "id": str(c.id),
        "name": c.name,
        "provider": c.provider.key,
        "provider_name": c.provider.name,
        "status": c.status,
        "status_message": c.status_message,
        "settings": c.settings,
        "credential_hint": hint,
        "credential_updated_at": updated,
        "last_sync_at": c.last_sync_at,
        "last_successful_sync_at": c.last_successful_sync_at,
        "last_error_at": c.last_error_at,
        "consecutive_failures": c.consecutive_failures,
        "created_at": c.created_at,
        "current_job": {"id": str(last_job.id), "status": last_job.status, "run_after": last_job.run_after} if last_job and last_job.status in ("queued", "running") else None,
    }


def _get(db: Session, user: User, cid: uuid.UUID) -> ExchangeConnection:
    c = db.get(ExchangeConnection, cid)
    if c is None or c.user_id != user.id:
        raise NotFound("Conexão não encontrada.")
    return c



def _validate(db: Session, c: ExchangeConnection, creds: dict) -> dict:
    """Valida a conexão na corretora e atualiza o estado. Retorna avisos."""
    adapter = build_adapter(c.provider.key, creds, c.settings)
    try:
        result = adapter.validate_credentials()
    except (InvalidCredentials, InsufficientPermissions) as exc:
        c.status, c.status_message = ConnectionStatus.INVALID_CREDENTIALS, redact_text(str(exc), 300)
        return {"ok": False, "message": c.status_message, "warnings": []}
    except (TemporaryError, AdapterError) as exc:
        c.status, c.status_message = ConnectionStatus.ERROR, redact_text(str(exc), 300)
        c.last_error_at = utcnow()
        return {"ok": False, "message": c.status_message, "warnings": []}
    finally:
        adapter.close()
    c.status, c.status_message = ConnectionStatus.ACTIVE, None
    return {"ok": True, "message": result.message, "warnings": result.warnings}


@router.get("/providers")
def providers(_: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    enabled = {p.key for p in db.scalars(select(ExchangeProvider).where(ExchangeProvider.enabled.is_(True)))}
    out = []
    for key, cls in ADAPTERS.items():
        if key not in enabled:
            continue
        i = cls.info
        out.append(
            {
                "key": i.key,
                "name": i.name,
                "docs_url": i.docs_url,
                "instructions": list(i.instructions),
                "credential_fields": [{"name": f.name, "label": f.label, "secret": f.secret, "help": f.help} for f in i.credential_fields],
                "capabilities": {
                    "balances": i.capabilities.balances,
                    "orders": i.capabilities.orders,
                    "executions": i.capabilities.executions,
                    "deposits": i.capabilities.deposits,
                    "withdrawals": i.capabilities.withdrawals,
                    "rate_limit": i.capabilities.rate_limit,
                    "notes": list(i.capabilities.notes),
                },
            }
        )
    return out


@router.get("/connections")
def list_connections(user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    rows = db.scalars(select(ExchangeConnection).where(ExchangeConnection.user_id == user.id).order_by(ExchangeConnection.created_at))
    return [_out(db, c) for c in rows]


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionIn, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    provider = db.scalar(select(ExchangeProvider).where(ExchangeProvider.key == body.provider, ExchangeProvider.enabled.is_(True)))
    if provider is None or body.provider not in ADAPTERS:
        raise AppError("Corretora não suportada.")
    creds = _validate_credential_fields(body.provider, body.credentials)
    c = ExchangeConnection(user_id=user.id, provider_id=provider.id, name=body.name.strip(), settings=body.settings.model_dump(exclude_none=True))
    c.provider = provider
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("Já existe uma conexão com esse nome.") from None
    store_secret(db, owner_type=CONNECTION_OWNER, owner_id=c.id, user_id=user.id, secret=creds, hint=_hint(creds))
    validation = _validate(db, c, creds)
    if validation["ok"]:
        enqueue_sync(db, c, trigger="initial", kind="full")
    audit(db, "integrations.connection_created", user_id=user.id, request=request, target_type="exchange_connection", target_id=c.id, provider=body.provider, valid=validation["ok"])
    db.commit()
    return {"connection": _out(db, c), "validation": validation}


@router.get("/connections/{cid}")
def get_connection(cid: uuid.UUID, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    return _out(db, _get(db, user, cid))


@router.patch("/connections/{cid}")
def patch_connection(cid: uuid.UUID, body: ConnectionPatch, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    c = _get(db, user, cid)
    if body.name:
        c.name = body.name.strip()
    if body.settings is not None:
        c.settings = body.settings.model_dump(exclude_none=True)
    try:
        audit(db, "integrations.connection_updated", user_id=user.id, request=request, target_type="exchange_connection", target_id=c.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("Já existe uma conexão com esse nome.") from None
    return _out(db, c)


@router.put("/connections/{cid}/credentials")
def replace_credentials(cid: uuid.UUID, body: CredentialsIn, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    """Substitui a credencial. O valor anterior nunca é exibido nem recuperado."""
    c = _get(db, user, cid)
    creds = _validate_credential_fields(c.provider.key, body.credentials)
    store_secret(db, owner_type=CONNECTION_OWNER, owner_id=c.id, user_id=user.id, secret=creds, hint=_hint(creds))
    was_suspended = c.status == ConnectionStatus.SUSPENDED
    validation = _validate(db, c, creds)
    if was_suspended and validation["ok"]:
        c.status = ConnectionStatus.SUSPENDED
    elif validation["ok"]:
        c.consecutive_failures = 0
        enqueue_sync(db, c, trigger="manual")
    audit(db, "integrations.credentials_replaced", user_id=user.id, request=request, target_type="exchange_connection", target_id=c.id, valid=validation["ok"])
    db.commit()
    return {"connection": _out(db, c), "validation": validation}


@router.post("/connections/{cid}/validate")
def revalidate(cid: uuid.UUID, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    from app.core.credentials import load_secret

    c = _get(db, user, cid)
    if c.status == ConnectionStatus.SUSPENDED:
        raise AppError("Reative a conexão antes de validá-la.")
    creds = load_secret(db, owner_type=CONNECTION_OWNER, owner_id=c.id, user_id=user.id)
    if not creds:
        raise AppError("Credencial não cadastrada.")
    validation = _validate(db, c, creds)
    audit(db, "integrations.connection_validated", user_id=user.id, request=request, target_type="exchange_connection", target_id=c.id, valid=validation["ok"])
    db.commit()
    return {"connection": _out(db, c), "validation": validation}


@router.post("/connections/{cid}/suspend")
def suspend(cid: uuid.UUID, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    c = _get(db, user, cid)
    c.status, c.suspended_at = ConnectionStatus.SUSPENDED, utcnow()
    for job in db.scalars(select(SyncJob).where(SyncJob.connection_id == c.id, SyncJob.status == "queued")):
        job.status, job.finished_at, job.error_message = "cancelled", utcnow(), "Conexão suspensa."
    audit(db, "integrations.connection_suspended", user_id=user.id, request=request, target_type="exchange_connection", target_id=c.id)
    db.commit()
    return _out(db, c)


@router.post("/connections/{cid}/resume")
def resume(cid: uuid.UUID, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    c = _get(db, user, cid)
    if c.status != ConnectionStatus.SUSPENDED:
        raise AppError("A conexão não está suspensa.")
    c.status, c.suspended_at, c.consecutive_failures = ConnectionStatus.PENDING, None, 0
    enqueue_sync(db, c, trigger="manual")
    audit(db, "integrations.connection_resumed", user_id=user.id, request=request, target_type="exchange_connection", target_id=c.id)
    db.commit()
    return _out(db, c)


@router.post("/connections/{cid}/sync", status_code=202)
def manual_sync(cid: uuid.UUID, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    c = _get(db, user, cid)
    if c.status in (ConnectionStatus.SUSPENDED, ConnectionStatus.INVALID_CREDENTIALS):
        raise AppError("Conexão suspensa ou com credencial inválida. Corrija antes de sincronizar.")
    job = enqueue_sync(db, c, trigger="manual")
    audit(db, "integrations.manual_sync", user_id=user.id, request=request, target_type="exchange_connection", target_id=c.id)
    db.commit()
    return {"job_id": str(job.id), "status": job.status}


@router.post("/sync-all", status_code=202)
def sync_all(request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    """Agenda sincronização manual de todas as conexões do usuário que podem sincronizar."""
    conns = db.scalars(select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)).all()
    queued, skipped = [], []
    for c in conns:
        if c.status in (ConnectionStatus.SUSPENDED, ConnectionStatus.INVALID_CREDENTIALS):
            skipped.append({"id": str(c.id), "name": c.name, "status": c.status})
            continue
        job = enqueue_sync(db, c, trigger="manual")
        db.flush()
        queued.append({"id": str(c.id), "name": c.name, "job_id": str(job.id)})
    audit(db, "integrations.manual_sync_all", user_id=user.id, request=request, queued=len(queued), skipped=len(skipped))
    db.commit()
    return {"queued": queued, "skipped": skipped}


@router.delete("/connections/{cid}", status_code=204)
def delete_connection(cid: uuid.UUID, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    c = _get(db, user, cid)
    delete_secret(db, CONNECTION_OWNER, c.id)
    db.delete(c)
    audit(db, "integrations.connection_deleted", user_id=user.id, request=request, target_type="exchange_connection", target_id=cid)
    db.commit()
    recalculate_user(db, user.id)


@router.get("/connections/{cid}/jobs")
def jobs(
    cid: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    only_errors: bool = False,
    user: User = Depends(require_permission(PERM)),
    db: Session = Depends(get_db),
):
    c = _get(db, user, cid)
    stmt = select(SyncJob).where(SyncJob.connection_id == c.id)
    if only_errors:
        stmt = stmt.where(SyncJob.error_message.is_not(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(SyncJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "total": total,
        "items": [
            {
                "id": str(j.id), "kind": j.kind, "trigger": j.trigger, "status": j.status, "attempts": j.attempts,
                "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
                "run_after": j.run_after, "error_message": j.error_message, "stats": j.stats,
            }
            for j in rows
        ],
    }

