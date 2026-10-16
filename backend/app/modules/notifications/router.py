from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.credentials import delete_secret, store_secret
from app.core.deps import require_permission
from app.core.errors import AppError, NotFound
from app.core.security import constant_time_equals, token_hash
from app.db import get_db
from app.models import NotificationChannel, NotificationEvent, NotificationPreference, User
from app.models.base import utcnow
from app.modules.notifications.base import EVENT_TYPES, ChannelError
from app.modules.notifications.service import CHANNEL_OWNER, channel_adapter, preference
from app.modules.notifications.telegram import build_telegram

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
PERM = "notifications:manage"
CODE_TTL = timedelta(minutes=30)


class TelegramIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    bot_token: str = Field(min_length=20, max_length=200)


class TokenIn(BaseModel):
    bot_token: str = Field(min_length=20, max_length=200)


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None


class PrefItem(BaseModel):
    event_type: str
    enabled: bool
    settings: dict = Field(default_factory=dict)


class PrefsIn(BaseModel):
    items: list[PrefItem]


def _hint(token: str) -> str:
    return token[-4:]


def _channel_out(ch: NotificationChannel) -> dict:
    cfg = ch.config or {}
    return {
        "id": str(ch.id),
        "kind": ch.kind,
        "name": ch.name,
        "status": ch.status,
        "enabled": ch.enabled,
        "bot_username": cfg.get("bot_username"),
        "chat_title": cfg.get("chat_title"),
        "chat_type": cfg.get("chat_type"),
        "verified_at": ch.verified_at,
        "last_error": ch.last_error,
        "token_hint": cfg.get("token_hint"),
        "created_at": ch.created_at,
    }


def _get_channel(db: Session, user: User, channel_id: uuid.UUID) -> NotificationChannel:
    ch = db.get(NotificationChannel, channel_id)
    if ch is None or ch.user_id != user.id:
        raise NotFound("Canal não encontrado.")
    return ch


def _new_code(ch: NotificationChannel) -> str:
    code = "TW-" + secrets.token_hex(4).upper()
    cfg = dict(ch.config or {})
    cfg["code_hash"] = token_hash(code)
    cfg["code_expires_at"] = (utcnow() + CODE_TTL).isoformat()
    ch.config = cfg
    return code


def _verification_payload(ch: NotificationChannel, code: str) -> dict:
    bot = (ch.config or {}).get("bot_username")
    return {
        "channel": _channel_out(ch),
        "verification_code": code,
        "expires_in_minutes": int(CODE_TTL.total_seconds() // 60),
        "instructions": [
            f"Chat privado: abra https://t.me/{bot} , toque em Iniciar e envie a mensagem: {code}",
            f"Grupo: adicione @{bot} ao grupo e envie no grupo: {code} (se o bot tiver privacidade ativa, use /start {code})",
            "Depois clique em 'Verificar destino'.",
        ],
    }


def _check_token(token: str) -> dict:
    tg = build_telegram(token)
    try:
        ident = tg.check()
    except ChannelError as exc:
        raise AppError(f"Não foi possível validar o bot: {exc}", code="channel_invalid") from None
    finally:
        tg.close()
    return ident.meta


@router.get("/event-types")
def event_types(_: User = Depends(require_permission(PERM))):
    return [{"key": k, "label": v} for k, v in EVENT_TYPES.items()]


@router.get("/channels")
def list_channels(user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    rows = db.scalars(select(NotificationChannel).where(NotificationChannel.user_id == user.id).order_by(NotificationChannel.created_at))
    return [_channel_out(c) for c in rows]


@router.post("/channels/telegram", status_code=201)
def create_telegram(body: TelegramIn, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    meta = _check_token(body.bot_token)
    ch = NotificationChannel(
        user_id=user.id,
        kind="telegram",
        name=body.name.strip(),
        status="pending_verification",
        enabled=False,
        config={"bot_username": meta.get("bot_username"), "bot_id": meta.get("bot_id"), "token_hint": _hint(body.bot_token)},
    )
    db.add(ch)
    db.flush()
    store_secret(db, owner_type=CHANNEL_OWNER, owner_id=ch.id, user_id=user.id, secret={"bot_token": body.bot_token}, hint=_hint(body.bot_token))
    code = _new_code(ch)
    audit(db, "notifications.channel_created", user_id=user.id, request=request, target_type="notification_channel", target_id=ch.id)
    db.commit()
    return _verification_payload(ch, code)


@router.post("/channels/{channel_id}/verification-code")
def new_code(channel_id: uuid.UUID, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    ch = _get_channel(db, user, channel_id)
    code = _new_code(ch)
    db.commit()
    return _verification_payload(ch, code)


@router.post("/channels/{channel_id}/verify")
def verify(channel_id: uuid.UUID, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    ch = _get_channel(db, user, channel_id)
    cfg = dict(ch.config or {})
    code_hash, expires = cfg.get("code_hash"), cfg.get("code_expires_at")
    if not code_hash or not expires or datetime.fromisoformat(expires) < utcnow():
        raise AppError("Código expirado. Gere um novo código.", code="code_expired")
    adapter = channel_adapter(db, ch)
    try:
        found = adapter.find_verification(lambda w: constant_time_equals(token_hash(w.strip().upper()), code_hash))
    except ChannelError as exc:
        raise AppError(str(exc), code="channel_error") from None
    if not found or found.get("chat_id") is None:
        raise AppError("Código ainda não recebido pelo bot. Envie o código no chat e tente novamente.", code="not_found_yet")
    cfg.update(found)
    cfg.pop("code_hash", None)
    cfg.pop("code_expires_at", None)
    ch.config = cfg
    ch.status, ch.enabled, ch.verified_at, ch.last_error = "active", True, utcnow(), None
    audit(db, "notifications.channel_verified", user_id=user.id, request=request, target_type="notification_channel", target_id=ch.id, chat_type=found.get("chat_type"))
    db.commit()
    try:
        adapter.send(ch.config, "✅ TradeWatch conectado. Você receberá as notificações selecionadas neste chat.")
    except ChannelError:
        pass
    return _channel_out(ch)


@router.post("/channels/{channel_id}/test")
def test_message(channel_id: uuid.UUID, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    ch = _get_channel(db, user, channel_id)
    if ch.status != "active":
        raise AppError("Verifique o destino antes de enviar a mensagem de teste.")
    ev = NotificationEvent(user_id=user.id, channel_id=ch.id, event_type="test", message="🔔 Mensagem de teste do TradeWatch.", attempts=1)
    db.add(ev)
    try:
        channel_adapter(db, ch).send(ch.config, ev.message)
        ev.status, ev.sent_at = "sent", utcnow()
    except ChannelError as exc:
        ev.status, ev.error = "failed", str(exc)
        ch.last_error = str(exc)
    db.commit()
    if ev.status != "sent":
        raise AppError(f"Falha no envio: {ev.error}", code="send_failed")
    return {"ok": True}


@router.patch("/channels/{channel_id}")
def patch_channel(channel_id: uuid.UUID, body: ChannelPatch, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    ch = _get_channel(db, user, channel_id)
    if body.enabled and ch.status != "active":
        raise AppError("Verifique o destino antes de ativar o canal.")
    if body.enabled is not None:
        ch.enabled = body.enabled
    if body.name:
        ch.name = body.name.strip()
    audit(db, "notifications.channel_updated", user_id=user.id, request=request, target_type="notification_channel", target_id=ch.id, **body.model_dump(exclude_none=True))
    db.commit()
    return _channel_out(ch)


@router.put("/channels/{channel_id}/token")
def replace_token(channel_id: uuid.UUID, body: TokenIn, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    ch = _get_channel(db, user, channel_id)
    meta = _check_token(body.bot_token)
    cfg = dict(ch.config or {})
    same_bot = cfg.get("bot_id") == meta.get("bot_id")
    cfg.update(bot_username=meta.get("bot_username"), bot_id=meta.get("bot_id"), token_hint=_hint(body.bot_token))
    code = None
    if not same_bot:
        # Outro bot: o destino precisa ser validado de novo.
        for k in ("chat_id", "chat_title", "chat_type"):
            cfg.pop(k, None)
        ch.status, ch.enabled, ch.verified_at = "pending_verification", False, None
    ch.config = cfg
    if not same_bot:
        code = _new_code(ch)
    store_secret(db, owner_type=CHANNEL_OWNER, owner_id=ch.id, user_id=user.id, secret={"bot_token": body.bot_token}, hint=_hint(body.bot_token))
    audit(db, "notifications.channel_token_replaced", user_id=user.id, request=request, target_type="notification_channel", target_id=ch.id, same_bot=same_bot)
    db.commit()
    return _verification_payload(ch, code) if code else {"channel": _channel_out(ch)}


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: uuid.UUID, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    ch = _get_channel(db, user, channel_id)
    delete_secret(db, CHANNEL_OWNER, ch.id)
    db.delete(ch)
    audit(db, "notifications.channel_deleted", user_id=user.id, request=request, target_type="notification_channel", target_id=channel_id)
    db.commit()


@router.get("/preferences")
def get_preferences(user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    out = []
    for key, label in EVENT_TYPES.items():
        enabled, settings = preference(db, user.id, key)
        out.append({"event_type": key, "label": label, "enabled": enabled, "settings": settings})
    return out


@router.put("/preferences")
def put_preferences(body: PrefsIn, request: Request, user: User = Depends(require_permission(PERM)), db: Session = Depends(get_db)):
    for item in body.items:
        if item.event_type not in EVENT_TYPES:
            raise AppError(f"Evento desconhecido: {item.event_type}")
        settings = {}
        if item.event_type == "daily_summary":
            hour = int(item.settings.get("hour", 20))
            if not 0 <= hour <= 23:
                raise AppError("Hora do resumo deve estar entre 0 e 23.")
            settings["hour"] = hour
        if item.event_type == "equity_change":
            pct = float(item.settings.get("threshold_pct", 5))
            if not 0.1 <= pct <= 100:
                raise AppError("Limite de variação deve estar entre 0,1% e 100%.")
            settings["threshold_pct"] = pct
        row = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id, NotificationPreference.event_type == item.event_type))
        if row is None:
            row = NotificationPreference(user_id=user.id, event_type=item.event_type)
            db.add(row)
        row.enabled, row.settings = item.enabled, settings
    audit(db, "notifications.preferences_updated", user_id=user.id, request=request)
    db.commit()
    return get_preferences(user, db)


@router.get("/events")
def list_events(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(require_permission(PERM)),
    db: Session = Depends(get_db),
):
    stmt = select(NotificationEvent).where(NotificationEvent.user_id == user.id)
    if status:
        stmt = stmt.where(NotificationEvent.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(NotificationEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "total": total,
        "items": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "label": EVENT_TYPES.get(e.event_type, e.event_type),
                "message": e.message,
                "status": e.status,
                "attempts": e.attempts,
                "error": e.error,
                "created_at": e.created_at,
                "sent_at": e.sent_at,
            }
            for e in rows
        ],
    }
