"""Emissão (outbox) e entrega de notificações.

Outros módulos chamam apenas ``emit``; a entrega é feita pelo worker em
``deliver_pending`` com retentativas e backoff, por qualquer canal registrado.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.credentials import load_secret
from app.core.redaction import redact_text
from app.models import NotificationChannel, NotificationEvent, NotificationPreference
from app.models.base import utcnow
from app.modules.notifications.base import DEFAULT_ENABLED, DEFAULT_SETTINGS, ChannelError, NotificationChannelAdapter
from app.modules.notifications.telegram import build_telegram

log = logging.getLogger("app.notifications")

CHANNEL_OWNER = "notification_channel"
MAX_ATTEMPTS = 5


def preference(db: Session, user_id: uuid.UUID, event_type: str) -> tuple[bool, dict]:
    row = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id, NotificationPreference.event_type == event_type
        )
    )
    defaults = DEFAULT_SETTINGS.get(event_type, {})
    if row is None:
        return DEFAULT_ENABLED.get(event_type, True), dict(defaults)
    return row.enabled, {**defaults, **(row.settings or {})}


def active_channels(db: Session, user_id: uuid.UUID) -> list[NotificationChannel]:
    return list(
        db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user_id,
                NotificationChannel.status == "active",
                NotificationChannel.enabled.is_(True),
            )
        )
    )


def emit(
    db: Session,
    user_id: uuid.UUID,
    event_type: str,
    message: str,
    payload: dict | None = None,
    *,
    dedupe_key: str | None = None,
    force: bool = False,
) -> int:
    """Enfileira a notificação para cada canal ativo. Não faz commit."""
    if not force:
        enabled, _ = preference(db, user_id, event_type)
        if not enabled:
            return 0
    n = 0
    for ch in active_channels(db, user_id):
        stmt = insert(NotificationEvent).values(
            id=uuid.uuid4(),
            user_id=user_id,
            channel_id=ch.id,
            event_type=event_type,
            payload=payload or {},
            message=message,
            status="pending",
            attempts=0,
            next_attempt_at=utcnow(),
            created_at=utcnow(),
            dedupe_key=f"{dedupe_key}:{ch.id}" if dedupe_key else None,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"]).returning(NotificationEvent.id)
        n += len(db.execute(stmt).all())
    return n


def channel_adapter(db: Session, ch: NotificationChannel) -> NotificationChannelAdapter:
    secret = load_secret(db, owner_type=CHANNEL_OWNER, owner_id=ch.id, user_id=ch.user_id)
    if not secret:
        raise ChannelError("Credencial do canal ausente.", permanent=True)
    if ch.kind == "telegram":
        return build_telegram(secret["bot_token"])
    raise ChannelError(f"Canal não suportado: {ch.kind}", permanent=True)


def deliver_pending(db: Session, limit: int = 50) -> int:
    events = db.scalars(
        select(NotificationEvent)
        .where(NotificationEvent.status == "pending", NotificationEvent.next_attempt_at <= utcnow())
        .order_by(NotificationEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    sent = 0
    adapters: dict[uuid.UUID, NotificationChannelAdapter] = {}
    for ev in events:
        ch = db.get(NotificationChannel, ev.channel_id) if ev.channel_id else None
        if ch is None or ch.status != "active" or not ch.enabled:
            ev.status = "skipped"
            ev.error = "Canal inativo."
            continue
        ev.attempts += 1
        try:
            adapter = adapters.get(ch.id) or channel_adapter(db, ch)
            adapters[ch.id] = adapter
            adapter.send(ch.config, ev.message)
            ev.status = "sent"
            ev.sent_at = utcnow()
            ev.error = None
            sent += 1
        except ChannelError as exc:
            ev.error = redact_text(str(exc), 500)
            if exc.permanent or ev.attempts >= MAX_ATTEMPTS:
                ev.status = "failed"
                ch.last_error = ev.error
            else:
                ev.next_attempt_at = utcnow() + timedelta(seconds=30 * 2**ev.attempts)
            log.warning("notification_failed", extra={"event_id": str(ev.id), "error": ev.error})
    db.commit()
    for a in adapters.values():
        if hasattr(a, "close"):
            a.close()
    return sent
