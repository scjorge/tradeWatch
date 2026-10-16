"""Rotas de consulta do módulo Trades: operações, ordens, posições, patrimônio, dashboard e relatórios."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.db import get_db
from app.models import (
    AssetMovement,
    ExchangeConnection,
    ExchangeOrder,
    RealizedPnlRecord,
    SyncJob,
    TradeExecution,
    User,
)
from app.models.base import utcnow
from app.modules.trades import analytics
from app.modules.trades.analytics import _f
from app.modules.trades.filters import Filters, apply_execution_filters, apply_realized_filters, filters_dep

router = APIRouter(prefix="/api/trades", tags=["trades"])
READ = "trades:read"

EXEC_SORT = {
    "executed_at": TradeExecution.executed_at,
    "symbol": TradeExecution.symbol,
    "side": TradeExecution.side,
    "quantity": TradeExecution.quantity,
    "price": TradeExecution.price,
    "quote_quantity": TradeExecution.quote_quantity,
    "fee": TradeExecution.fee,
}


def _exec_out(e: TradeExecution) -> dict:
    return {
        "id": str(e.id),
        "executed_at": e.executed_at,
        "provider": e.connection.provider.key,
        "connection_id": str(e.connection_id),
        "connection_name": e.connection.name,
        "market": e.market,
        "symbol": e.symbol,
        "base_asset": e.base_asset,
        "quote_asset": e.quote_asset,
        "side": e.side,
        "quantity": _f(e.quantity),
        "price": _f(e.price),
        "gross_value": _f(e.quote_quantity),
        "fee": _f(e.fee),
        "fee_asset": e.fee_asset,
        "fee_value": _f(e.fee_value),
        "fee_value_currency": e.fee_value_currency,
        "net_value": _f(e.quote_quantity - e.fee if e.fee_asset == e.quote_asset else e.quote_quantity)
        if e.side == "SELL"
        else _f(e.quote_quantity + e.fee if e.fee_asset == e.quote_asset else e.quote_quantity),
        "external_id": e.external_id,
        "external_order_id": e.external_order_id,
        "order_id": str(e.order_id) if e.order_id else None,
        "source": e.source,
        "sync_status": e.sync_status,
    }


def _exec_query(user: User, f: Filters, sort: str, direction: str):
    col = EXEC_SORT.get(sort, TradeExecution.executed_at)
    stmt = apply_execution_filters(select(TradeExecution).where(TradeExecution.user_id == user.id), f)
    return stmt.order_by(col.desc() if direction == "desc" else col.asc(), TradeExecution.id)


@router.get("/executions")
def list_executions(
    f: Filters = Depends(filters_dep),
    sort: str = Query("executed_at"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    stmt = _exec_query(user, f, sort, direction)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_exec_out(e) for e in rows]}


def _csv_safe(v) -> str:
    """Evita injeção de fórmulas em planilhas."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(s) else s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


@router.get("/executions.csv")
def export_executions(
    f: Filters = Depends(filters_dep),
    sort: str = Query("executed_at"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    cols = [
        "executed_at", "provider", "connection_name", "market", "symbol", "side", "quantity", "price",
        "gross_value", "fee", "fee_asset", "fee_value", "fee_value_currency", "net_value", "external_id",
        "external_order_id", "source", "sync_status",
    ]
    rows = db.scalars(_exec_query(user, f, sort, direction).limit(100_000)).all()

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for e in rows:
            d = _exec_out(e)
            d["executed_at"] = e.executed_at.isoformat()
            w.writerow([_csv_safe(d[c]) for c in cols])
            if buf.tell() > 64_000:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    name = f"operacoes-{utcnow():%Y%m%d-%H%M}.csv"
    return StreamingResponse(gen(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/orders")
def list_orders(
    f: Filters = Depends(filters_dep),
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    Ord = ExchangeOrder
    stmt = select(Ord).where(Ord.user_id == user.id)
    if f.start:
        stmt = stmt.where(Ord.placed_at >= f.start)
    if f.end:
        stmt = stmt.where(Ord.placed_at <= f.end)
    if f.connection_ids:
        stmt = stmt.where(Ord.connection_id.in_(f.connection_ids))
    if f.symbol:
        stmt = stmt.where(Ord.symbol == f.symbol)
    if f.asset:
        stmt = stmt.where((Ord.base_asset == f.asset) | (Ord.quote_asset == f.asset))
    if f.side:
        stmt = stmt.where(Ord.side == f.side)
    if status:
        stmt = stmt.where(Ord.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Ord.placed_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    fills = dict(
        db.execute(
            select(TradeExecution.order_id, func.count()).where(TradeExecution.order_id.in_([o.id for o in rows])).group_by(TradeExecution.order_id)
        ).all()
    ) if rows else {}
    return {
        "total": total,
        "items": [
            {
                "id": str(o.id), "external_id": o.external_id, "connection_id": str(o.connection_id), "symbol": o.symbol,
                "side": o.side, "type": o.order_type, "status": o.status, "price": _f(o.price), "orig_qty": _f(o.orig_qty),
                "executed_qty": _f(o.executed_qty), "cumulative_quote_qty": _f(o.cumulative_quote_qty),
                "placed_at": o.placed_at, "updated_at": o.exchange_updated_at, "executions": fills.get(o.id, 0),
            }
            for o in rows
        ],
    }


@router.get("/movements")
def list_movements(
    f: Filters = Depends(filters_dep),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    M = AssetMovement
    stmt = select(M).where(M.user_id == user.id)
    if f.start:
        stmt = stmt.where(M.occurred_at >= f.start)
    if f.end:
        stmt = stmt.where(M.occurred_at <= f.end)
    if f.connection_ids:
        stmt = stmt.where(M.connection_id.in_(f.connection_ids))
    if f.asset:
        stmt = stmt.where(M.asset == f.asset)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(M.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "total": total,
        "items": [
            {
                "id": str(m.id), "kind": m.kind, "asset": m.asset, "amount": _f(m.amount), "fee": _f(m.fee),
                "network": m.network, "tx_id": m.tx_id, "status": m.status, "occurred_at": m.occurred_at,
                "connection_id": str(m.connection_id),
            }
            for m in rows
        ],
    }


@router.get("/positions")
def positions(user: User = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return analytics.positions_view(db, user)


@router.get("/pnl/summary")
def pnl_summary(f: Filters = Depends(filters_dep), user: User = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return analytics.realized_summary(db, user, f)


@router.get("/pnl/realized")
def realized_records(
    f: Filters = Depends(filters_dep),
    status: str | None = Query(None, pattern="^(complete|incomplete)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    R = RealizedPnlRecord
    stmt = apply_realized_filters(select(R).where(R.user_id == user.id), f)
    if status:
        stmt = stmt.where(R.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(R.realized_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {
        "total": total,
        "items": [
            {
                "id": str(r.id), "kind": r.kind, "asset": r.asset, "quantity": _f(r.quantity), "proceeds": _f(r.proceeds),
                "cost_basis": _f(r.cost_basis), "fees": _f(r.fees), "realized_pnl": _f(r.realized_pnl), "status": r.status,
                "note": r.note, "method": r.method, "base_currency": r.base_currency, "realized_at": r.realized_at,
                "execution_id": str(r.execution_id) if r.execution_id else None,
            }
            for r in rows
        ],
    }


@router.get("/pnl/by-period")
def pnl_by_period(
    f: Filters = Depends(filters_dep),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    return {"base_currency": user.base_currency, "granularity": granularity, "items": analytics.pnl_by_period(db, user, f, granularity)}


@router.post("/recalculate")
def recalculate(user: User = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    from app.modules.trades.pnl.service import recalculate_user

    r = recalculate_user(db, user.id)
    return {"records": len(r.realized), "positions": len(r.positions), "warnings": r.warnings}


# ---------------------------------------------------------------- patrimônio
portfolio = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@portfolio.get("/balances")
def balances(f: Filters = Depends(filters_dep), user: User = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return analytics.holdings(db, user, f.connection_ids)


@portfolio.get("/history")
def history(f: Filters = Depends(filters_dep), user: User = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    start = f.start or utcnow() - timedelta(days=90)
    return {"base_currency": user.base_currency, "items": analytics.equity_history(db, user, start, f.end, f.connection_ids)}


@portfolio.get("/compare")
def compare(
    a: datetime = Query(..., description="Data inicial"),
    b: datetime = Query(..., description="Data final"),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    series = analytics.equity_history(db, user, None, None)

    def at(d: datetime):
        key = d.date().isoformat()
        candidates = [p for p in series if p["date"] <= key]
        return candidates[-1] if candidates else None

    pa, pb = at(a), at(b)
    change = pct = None
    if pa and pb and pa["value"] is not None and pb["value"] is not None:
        from decimal import Decimal

        va, vb = Decimal(pa["value"]), Decimal(pb["value"])
        change = _f(vb - va)
        pct = float((vb - va) / va * 100) if va else None
    return {"base_currency": user.base_currency, "a": pa, "b": pb, "change": change, "change_pct": pct,
            "note": "Variação de patrimônio inclui aportes e retiradas; não é rentabilidade."}


# ---------------------------------------------------------------- dashboard
dashboard = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@dashboard.get("")
def overview(f: Filters = Depends(filters_dep), user: User = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    conns = db.scalars(select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)).all()
    last_jobs = {
        j.connection_id: j
        for j in db.scalars(
            select(SyncJob)
            .where(SyncJob.user_id == user.id)
            .distinct(SyncJob.connection_id)
            .order_by(SyncJob.connection_id, SyncJob.created_at.desc())
        )
    }
    pos = analytics.positions_view(db, user)
    last_sync = max((c.last_successful_sync_at for c in conns if c.last_successful_sync_at), default=None)
    return {
        "base_currency": user.base_currency,
        "method": user.cost_method,
        "holdings": analytics.holdings(db, user, f.connection_ids),
        "realized": analytics.realized_summary(db, user, f),
        "unrealized": {"total": pos["unrealized_total"], "complete": pos["unrealized_complete"], "open_cost_basis": pos["open_cost_basis"]},
        "equity_history": analytics.equity_history(db, user, f.start or utcnow() - timedelta(days=90), f.end, f.connection_ids),
        "pnl_by_period": analytics.pnl_by_period(db, user, f, "day" if (f.start and (f.end or utcnow()) - f.start <= timedelta(days=62)) else "month"),
        "recent_activity": analytics.recent_activity(db, user),
        "integrations": [
            {
                "id": str(c.id), "name": c.name, "provider": c.provider.key, "status": c.status, "status_message": c.status_message,
                "last_successful_sync_at": c.last_successful_sync_at,
                "last_job_status": last_jobs[c.id].status if c.id in last_jobs else None,
            }
            for c in conns
        ],
        "last_sync_at": last_sync,
    }
