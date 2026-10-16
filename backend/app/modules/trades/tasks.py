"""Tarefas periódicas do módulo Trades (executadas pelo worker)."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ConnectionStatus, ExchangeConnection, SyncJob, User
from app.models.base import utcnow
from app.modules.notifications import service as notify
from app.modules.trades import analytics
from app.modules.trades.filters import Filters
from app.modules.trades.sync import enqueue_sync, requeue_stale_jobs

log = logging.getLogger("app.trades.tasks")


def schedule_periodic_syncs(db: Session) -> None:
    requeue_stale_jobs(db)
    interval = timedelta(minutes=get_settings().sync_interval_minutes)
    now = utcnow()
    conns = db.scalars(
        select(ExchangeConnection).where(ExchangeConnection.status.in_((ConnectionStatus.ACTIVE, ConnectionStatus.ERROR)))
    ).all()
    for c in conns:
        last = c.last_sync_at
        if last is not None and now - last < interval:
            continue
        # Conexões com erro recorrente esperam mais (até 6h) para não martelar a corretora.
        if c.status == ConnectionStatus.ERROR and last and now - last < min(interval * (2 ** min(c.consecutive_failures, 5)), timedelta(hours=6)):
            continue
        busy = db.scalar(select(SyncJob.id).where(SyncJob.connection_id == c.id, SyncJob.status.in_(("queued", "running"))).limit(1))
        if not busy:
            enqueue_sync(db, c, trigger="schedule")
    db.commit()


def _users_with_channels(db: Session) -> list[User]:
    from app.models import NotificationChannel

    ids = db.scalars(
        select(NotificationChannel.user_id).where(NotificationChannel.status == "active", NotificationChannel.enabled.is_(True)).distinct()
    ).all()
    return list(db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True)))) if ids else []


def daily_summaries(db: Session) -> None:
    now = utcnow()
    for user in _users_with_channels(db):
        enabled, settings = notify.preference(db, user.id, "daily_summary")
        if not enabled:
            continue
        local = now.astimezone(ZoneInfo(user.timezone))
        if local.hour != int(settings.get("hour", 20)):
            continue
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        s = analytics.realized_summary(db, user, Filters(start=day_start, end=now))
        h = analytics.holdings(db, user)
        r = user.base_currency
        lines = [
            f"📊 Resumo de {local:%d/%m/%Y}",
            f"Patrimônio estimado: {h['total_value']} {r}" + ("" if h["complete"] else " (parcial: ativos sem cotação)"),
            f"Resultado realizado hoje: {s['realized_net']} {r}" + (f" ({s['records_incomplete']} registro(s) incompleto(s))" if s["records_incomplete"] else ""),
            f"Taxas pagas hoje: {s['fees_paid']} {r}",
            f"Execuções hoje: {s['executions_count']}",
        ]
        notify.emit(db, user.id, "daily_summary", "\n".join(lines), {"date": local.date().isoformat()}, dedupe_key=f"daily:{user.id}:{local.date()}")
    db.commit()


def equity_alerts(db: Session) -> None:
    now = utcnow()
    for user in _users_with_channels(db):
        enabled, settings = notify.preference(db, user.id, "equity_change")
        if not enabled:
            continue
        threshold = Decimal(str(settings.get("threshold_pct", 5)))
        series = analytics.equity_history(db, user, now - timedelta(days=2), now)
        if len(series) < 2 or not series[-1]["complete"] or not series[-2]["complete"]:
            continue
        prev, cur = Decimal(series[-2]["value"]), Decimal(series[-1]["value"])
        if not prev:
            continue
        pct = (cur - prev) / prev * 100
        if abs(pct) >= threshold:
            direction = "up" if pct > 0 else "down"
            notify.emit(
                db, user.id, "equity_change",
                f"{'📈' if pct > 0 else '📉'} Patrimônio variou {pct:.2f}% desde o último dia ({prev:.2f} → {cur:.2f} {user.base_currency}). "
                "A variação inclui aportes/retiradas.",
                {"pct": float(pct)},
                dedupe_key=f"equity:{user.id}:{series[-1]['date']}:{direction}",
            )
    db.commit()


def refresh_open_prices(db: Session) -> None:
    """Mantém cotações das posições "Ativo" (inclusive lançamentos manuais, que não sincronizam)."""
    from app.integrations.base import TemporaryError
    from app.integrations.registry import build_price_source
    from app.models import CycleStatus, TradeCycle
    from app.modules.trades.pricing import refresh_current_prices

    rows = db.execute(
        select(TradeCycle.asset, TradeCycle.buy_quote).where(TradeCycle.status.in_((CycleStatus.OPEN, CycleStatus.SELL_ORDER))).distinct()
    ).all()
    if not rows:
        return
    quotes = {q for _, q in rows if q} | {"BRL", "USDT"}
    source = build_price_source()
    try:
        refresh_current_prices(db, source, {a for a, _ in rows} | quotes, quotes)
    except TemporaryError as exc:
        db.rollback()
        log.warning("open_prices_unavailable", extra={"error": str(exc)})
    finally:
        if hasattr(source, "close"):
            source.close()
