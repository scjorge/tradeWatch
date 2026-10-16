"""Administração da plataforma. Administradores não têm acesso a credenciais dos usuários."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.deps import require_permission
from app.core.errors import AppError, NotFound
from app.db import get_db
from app.models import AuditLog, ExchangeConnection, Module, Role, SyncJob, User
from app.models.base import utcnow
from app.modules.auth.service import revoke_user_sessions

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserPatch(BaseModel):
    is_active: bool | None = None
    roles: list[str] | None = None


class ModulePatch(BaseModel):
    enabled: bool


@router.get("/users")
def list_users(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: User = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
):
    stmt = select(User)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    conn_counts = dict(
        db.execute(select(ExchangeConnection.user_id, func.count()).group_by(ExchangeConnection.user_id)).all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
                "is_active": u.is_active,
                "email_verified": u.email_verified_at is not None,
                "roles": u.role_keys,
                "created_at": u.created_at,
                "last_login_at": u.last_login_at,
                "connections": conn_counts.get(u.id, 0),
            }
            for u in rows
        ],
    }


@router.patch("/users/{user_id}")
def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    request: Request,
    admin: User = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("Usuário não encontrado.")
    if user.id == admin.id and (body.is_active is False or (body.roles is not None and "admin" not in body.roles)):
        raise AppError("Você não pode desativar nem remover o próprio papel de administrador.")
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            revoke_user_sessions(db, user.id)
    if body.roles is not None:
        roles = db.scalars(select(Role).where(Role.key.in_(body.roles))).all()
        if len(roles) != len(set(body.roles)):
            raise AppError("Papel inexistente.")
        user.roles = list(roles)
    audit(
        db,
        "admin.user_updated",
        user_id=admin.id,
        request=request,
        target_type="user",
        target_id=user.id,
        changes=body.model_dump(exclude_none=True),
    )
    db.commit()
    return {"ok": True}


@router.get("/modules")
def list_modules(_: User = Depends(require_permission("admin:modules")), db: Session = Depends(get_db)):
    from app.modules.registry import REGISTRY

    core = {m.key for m in REGISTRY if m.core}
    return [
        {
            "key": m.key,
            "name": m.name,
            "description": m.description,
            "version": m.version,
            "enabled": m.enabled,
            "core": m.key in core,
        }
        for m in db.scalars(select(Module).order_by(Module.key))
    ]


@router.patch("/modules/{key}")
def patch_module(
    key: str,
    body: ModulePatch,
    request: Request,
    admin: User = Depends(require_permission("admin:modules")),
    db: Session = Depends(get_db),
):
    from app.modules.registry import REGISTRY

    mod = db.scalar(select(Module).where(Module.key == key))
    if mod is None:
        raise NotFound("Módulo não encontrado.")
    if not body.enabled and any(m.core and m.key == key for m in REGISTRY):
        raise AppError("Módulos de núcleo não podem ser desativados.")
    mod.enabled = body.enabled
    audit(db, "admin.module_updated", user_id=admin.id, request=request, target_type="module", target_id=key, enabled=body.enabled)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def list_audit(
    action: str | None = None,
    user_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: User = Depends(require_permission("admin:audit")),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "total": total,
        "items": [
            {
                "id": str(a.id),
                "user_id": str(a.user_id) if a.user_id else None,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "ip": a.ip,
                "details": a.details,
                "created_at": a.created_at,
            }
            for a in rows
        ],
    }


@router.get("/metrics")
def metrics(_: User = Depends(require_permission("admin:metrics")), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(hours=24)
    by_status = dict(
        db.execute(
            select(SyncJob.status, func.count()).where(SyncJob.created_at >= since).group_by(SyncJob.status)
        ).all()
    )
    avg_duration = db.scalar(
        select(func.avg(func.extract("epoch", SyncJob.finished_at - SyncJob.started_at))).where(
            SyncJob.created_at >= since, SyncJob.status == "succeeded"
        )
    )
    conn_status = dict(
        db.execute(select(ExchangeConnection.status, func.count()).group_by(ExchangeConnection.status)).all()
    )
    failing = db.scalar(select(func.count()).where(ExchangeConnection.consecutive_failures >= 3))
    return {
        "window_hours": 24,
        "sync_jobs_by_status": by_status,
        "sync_avg_duration_seconds": float(avg_duration) if avg_duration is not None else None,
        "connections_by_status": conn_status,
        "connections_with_repeated_failures": failing,
        "users": db.scalar(select(func.count()).select_from(User)),
    }
