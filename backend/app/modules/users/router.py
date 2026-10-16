from __future__ import annotations

import json
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.deps import current_user, get_current_session
from app.core.errors import AppError, NotFound
from app.db import get_db
from app.models import Module, User, UserModuleSetting, UserSession
from app.models.base import utcnow
from app.modules.auth import service as auth_service
from app.modules.users.schemas import UserOut, user_out

router = APIRouter(prefix="/api/me", tags=["me"])

# Moeda padrão da plataforma: real ou dólar (USDT, a referência de dólar nas corretoras de cripto).
SUPPORTED_BASE_CURRENCIES = ("BRL", "USDT")
COST_METHODS = ("FIFO", "AVERAGE")


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    base_currency: str | None = None
    cost_method: str | None = None


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.get("", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.patch("", response_model=UserOut)
def update_me(body: ProfileIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user = db.get(User, user.id)
    changes = body.model_dump(exclude_none=True)
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise AppError("Fuso horário inválido.") from exc
    if "base_currency" in changes and changes["base_currency"] not in SUPPORTED_BASE_CURRENCIES:
        raise AppError("Moeda não suportada. Use BRL ou USDT (dólar).")
    if "cost_method" in changes and changes["cost_method"] not in COST_METHODS:
        raise AppError("Método de custo inválido.")
    recalc = any(k in changes and changes[k] != getattr(user, k) for k in ("base_currency", "cost_method"))
    for k, v in changes.items():
        setattr(user, k, v.strip() if isinstance(v, str) else v)
    audit(db, "user.profile_updated", user_id=user.id, request=request, fields=sorted(changes))
    db.commit()
    if recalc:
        from app.integrations.registry import build_price_source
        from app.modules.trades.pnl.service import recalculate_user

        # Com a fonte de cotações, o câmbio histórico que faltar para a nova moeda é buscado agora.
        source = build_price_source()
        try:
            recalculate_user(db, user.id, source)
        finally:
            if hasattr(source, "close"):
                source.close()
    return user_out(user)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordIn,
    request: Request,
    sess: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user = db.get(User, sess.user_id)
    auth_service.change_password(db, user, body.current_password, body.new_password, sess.id, request)


@router.get("/sessions")
def list_sessions(sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    now = utcnow()
    rows = db.scalars(
        select(UserSession)
        .where(UserSession.user_id == sess.user_id, UserSession.revoked_at.is_(None), UserSession.expires_at > now)
        .order_by(UserSession.last_seen_at.desc())
    ).all()
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at,
            "last_seen_at": r.last_seen_at,
            "ip": r.ip,
            "user_agent": r.user_agent,
            "current": r.id == sess.id,
        }
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    sess: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    target = db.get(UserSession, session_id)
    if target is None or target.user_id != sess.user_id:
        raise NotFound("Sessão não encontrada.")
    target.revoked_at = utcnow()
    audit(db, "auth.session_revoked", user_id=sess.user_id, request=request, target_type="session", target_id=session_id)
    db.commit()


@router.post("/sessions/revoke-others")
def revoke_others(request: Request, sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    n = auth_service.revoke_user_sessions(db, sess.user_id, except_session_id=sess.id)
    audit(db, "auth.sessions_revoked", user_id=sess.user_id, request=request, count=n)
    db.commit()
    return {"revoked": n}


@router.get("/modules")
def my_modules(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Módulos habilitados e itens de navegação permitidos ao usuário."""
    from app.modules.registry import REGISTRY

    enabled = {m.key: m for m in db.scalars(select(Module)).all()}
    user_settings = {
        s.module_id: s for s in db.scalars(select(UserModuleSetting).where(UserModuleSetting.user_id == user.id))
    }
    perms = user.permission_keys
    out = []
    for spec in REGISTRY:
        row = enabled.get(spec.key)
        if row is None or not row.enabled:
            continue
        us = user_settings.get(row.id)
        out.append(
            {
                "key": spec.key,
                "name": spec.name,
                "user_enabled": us.enabled if us else True,
                "nav": [
                    {"label": n.label, "path": n.path, "icon": n.icon, "order": n.order}
                    for n in spec.nav
                    if n.permission is None or n.permission in perms
                ],
            }
        )
    return out


# ---------------------------------------------------------------- preferências por módulo
MAX_SETTINGS_BYTES = 16 * 1024


class ModuleSettingsIn(BaseModel):
    # Chaves de primeiro nível são mescladas com as já salvas; valor null remove a chave.
    settings: dict


def _module_or_404(db: Session, key: str) -> Module:
    mod = db.scalar(select(Module).where(Module.key == key))
    if mod is None or not mod.enabled:
        raise NotFound("Módulo não encontrado.")
    return mod


@router.get("/modules/{key}/settings")
def get_module_settings(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Preferências do usuário para o módulo (ex.: colunas visíveis), salvas no perfil."""
    mod = _module_or_404(db, key)
    row = db.scalar(select(UserModuleSetting).where(UserModuleSetting.user_id == user.id, UserModuleSetting.module_id == mod.id))
    return {"module": key, "settings": row.settings if row else {}}


@router.patch("/modules/{key}/settings")
def patch_module_settings(key: str, body: ModuleSettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    mod = _module_or_404(db, key)
    for k in body.settings:
        if not re.fullmatch(r"[a-z][a-z0-9_.]{0,63}", k):
            raise AppError(f"Chave de preferência inválida: {k[:40]}")
    row = db.scalar(select(UserModuleSetting).where(UserModuleSetting.user_id == user.id, UserModuleSetting.module_id == mod.id))
    if row is None:
        row = UserModuleSetting(user_id=user.id, module_id=mod.id, settings={})
        db.add(row)
    merged = {**(row.settings or {}), **body.settings}
    merged = {k: v for k, v in merged.items() if v is not None}
    if len(json.dumps(merged)) > MAX_SETTINGS_BYTES:
        raise AppError("Preferências grandes demais.")
    row.settings = merged
    db.commit()
    return {"module": key, "settings": merged}
