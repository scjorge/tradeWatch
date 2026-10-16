"""Consultas analíticas: patrimônio, resultados e séries históricas.

Convenções:
- Patrimônio = saldo informado pela corretora × cotação mais recente (fonte e horário retornados).
- Resultado realizado líquido = soma de ``realized_pnl`` dos registros completos (taxas já embutidas).
- Resultado bruto = líquido + taxas pagas no período (valor das taxas na moeda-base).
- Resultado não realizado = Σ(qtd × cotação − custo) apenas para posições com custo conhecido.
- Valores sem base confiável são retornados como ``None`` e marcados como incompletos.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Balance,
    BalanceSnapshot,
    ExchangeConnection,
    Position,
    RealizedPnlRecord,
    TradeExecution,
    User,
)
from app.modules.trades.filters import Filters, apply_execution_filters, apply_realized_filters
from app.modules.trades.pricing import CurrentPrices

ZERO = Decimal(0)


def _f(v: Decimal | None) -> str | None:
    """Decimais trafegam como string para não perder precisão no JSON."""
    return None if v is None else format(Decimal(v).normalize(), "f")


def holdings(db: Session, user: User, connection_ids: list[uuid.UUID] | None = None) -> dict:
    stmt = select(Balance, ExchangeConnection).join(ExchangeConnection, Balance.connection_id == ExchangeConnection.id).where(
        Balance.user_id == user.id
    )
    if connection_ids:
        stmt = stmt.where(Balance.connection_id.in_(connection_ids))
    prices = CurrentPrices(db)
    r = user.base_currency
    rows, total, unpriced = [], ZERO, []
    by_asset: dict[str, dict] = {}
    by_conn: dict[str, dict] = {}
    for bal, conn in db.execute(stmt).all():
        q = prices.get(bal.asset, r)
        value = bal.total * q.price if q else None
        if value is not None:
            total += value
        else:
            unpriced.append(bal.asset)
        rows.append(
            {
                "connection_id": str(conn.id),
                "connection_name": conn.name,
                "provider": conn.provider.key,
                "asset": bal.asset,
                "free": _f(bal.free),
                "locked": _f(bal.locked),
                "total": _f(bal.total),
                "reported_at": bal.reported_at,
                "price": _f(q.price) if q else None,
                "price_source": q.source if q else None,
                "price_at": q.at if q else None,
                "value": _f(value),
            }
        )
        a = by_asset.setdefault(bal.asset, {"asset": bal.asset, "quantity": ZERO, "value": ZERO, "priced": True})
        a["quantity"] += bal.total
        if value is None:
            a["priced"] = False
        else:
            a["value"] += value
        c = by_conn.setdefault(str(conn.id), {"connection_id": str(conn.id), "name": conn.name, "provider": conn.provider.key, "value": ZERO})
        c["value"] += value or ZERO
    assets = sorted(by_asset.values(), key=lambda x: x["value"], reverse=True)
    for a in assets:
        a["share_pct"] = float(a["value"] / total * 100) if total else None
        a["quantity"], a["value"] = _f(a["quantity"]), _f(a["value"]) if a["priced"] else None
    conns = sorted(by_conn.values(), key=lambda x: x["value"], reverse=True)
    for c in conns:
        c["value"] = _f(c["value"])
    return {
        "base_currency": r,
        "total_value": _f(total),
        "complete": not unpriced,
        "unpriced_assets": sorted(set(unpriced)),
        "rows": rows,
        "by_asset": assets,
        "by_connection": conns,
    }


def positions_view(db: Session, user: User) -> dict:
    """Posições calculadas localmente, com resultado não realizado e conciliação com o saldo da corretora."""
    prices = CurrentPrices(db)
    reported = dict(
        db.execute(select(Balance.asset, func.sum(Balance.total)).where(Balance.user_id == user.id).group_by(Balance.asset)).all()
    )
    out, unrealized_total, open_cost, incomplete = [], ZERO, ZERO, False
    for p in db.scalars(select(Position).where(Position.user_id == user.id).order_by(Position.asset)):
        q = prices.get(p.asset, user.base_currency)
        market_value = p.quantity * q.price if q else None
        unrealized = None
        if q and p.cost_basis is not None and p.asset != user.base_currency:
            unrealized = market_value - p.cost_basis
            unrealized_total += unrealized
            open_cost += p.cost_basis
        elif p.asset != user.base_currency:
            incomplete = True
        rep = reported.get(p.asset)
        out.append(
            {
                "asset": p.asset,
                "quantity": _f(p.quantity),
                "reported_quantity": _f(rep) if rep is not None else None,
                "difference": _f(rep - p.quantity) if rep is not None else None,
                "cost_basis": _f(p.cost_basis),
                "avg_cost": _f(p.cost_basis / p.quantity) if p.cost_basis is not None and p.quantity else None,
                "cost_basis_complete": p.cost_basis_complete,
                "unknown_cost_quantity": _f(p.unknown_cost_quantity),
                "price": _f(q.price) if q else None,
                "price_source": q.source if q else None,
                "price_at": q.at if q else None,
                "market_value": _f(market_value),
                "unrealized_pnl": _f(unrealized),
                "unrealized_pct": float(unrealized / p.cost_basis * 100) if unrealized is not None and p.cost_basis else None,
                "method": p.method,
                "computed_at": p.computed_at,
            }
        )
    return {
        "base_currency": user.base_currency,
        "method": user.cost_method,
        "positions": out,
        "unrealized_total": _f(unrealized_total),
        "unrealized_complete": not incomplete,
        "open_cost_basis": _f(open_cost),
    }


def realized_summary(db: Session, user: User, f: Filters) -> dict:
    stmt = apply_realized_filters(select(RealizedPnlRecord).where(RealizedPnlRecord.user_id == user.id), f)
    records = db.scalars(stmt).all()
    complete = [r for r in records if r.status == "complete" and r.realized_pnl is not None]
    sales = [r for r in complete if r.kind == "sale"]
    wins = [r for r in sales if r.realized_pnl > 0]
    losses = [r for r in sales if r.realized_pnl < 0]
    net = sum((r.realized_pnl for r in complete), ZERO)
    cost = sum((r.cost_basis or ZERO for r in complete), ZERO)

    fee_stmt = apply_execution_filters(
        select(func.sum(TradeExecution.fee_value), func.count(), func.count(TradeExecution.fee_value)).where(TradeExecution.user_id == user.id), f
    )
    fees, n_exec, n_fee_known = db.execute(fee_stmt).one()
    fees = fees or ZERO

    def rec(r: RealizedPnlRecord | None):
        if r is None:
            return None
        return {"asset": r.asset, "realized_pnl": _f(r.realized_pnl), "realized_at": r.realized_at, "execution_id": str(r.execution_id) if r.execution_id else None}

    best = max(sales, key=lambda r: r.realized_pnl, default=None)
    worst = min(sales, key=lambda r: r.realized_pnl, default=None)
    return {
        "base_currency": user.base_currency,
        "method": user.cost_method,
        "realized_net": _f(net),
        "fees_paid": _f(fees),
        "fees_complete": n_fee_known == n_exec,
        "realized_gross": _f(net + fees),
        "realized_return_pct": float(net / cost * 100) if cost else None,
        "records_total": len(records),
        "records_incomplete": len(records) - len(complete),
        "executions_count": n_exec,
        "closed_operations": len(sales),
        "win_rate_pct": float(len(wins) / len(sales) * 100) if sales else None,
        "avg_gain": _f(sum((r.realized_pnl for r in wins), ZERO) / len(wins)) if wins else None,
        "avg_loss": _f(sum((r.realized_pnl for r in losses), ZERO) / len(losses)) if losses else None,
        "best": rec(best),
        "worst": rec(worst),
    }


def _period_key(dt: datetime, tz: ZoneInfo, granularity: str) -> str:
    d = dt.astimezone(tz).date()
    if granularity == "month":
        return d.strftime("%Y-%m")
    if granularity == "week":
        start = d - timedelta(days=d.weekday())
        return start.isoformat()
    return d.isoformat()


def pnl_by_period(db: Session, user: User, f: Filters, granularity: str = "day") -> list[dict]:
    tz = ZoneInfo(user.timezone)
    stmt = apply_realized_filters(select(RealizedPnlRecord).where(RealizedPnlRecord.user_id == user.id), f)
    buckets: dict[str, dict] = defaultdict(lambda: {"realized": ZERO, "incomplete": 0, "operations": 0, "fees": ZERO})
    for r in db.scalars(stmt):
        b = buckets[_period_key(r.realized_at, tz, granularity)]
        if r.status == "complete" and r.realized_pnl is not None:
            b["realized"] += r.realized_pnl
        else:
            b["incomplete"] += 1
        if r.kind == "sale":
            b["operations"] += 1
    fee_stmt = apply_execution_filters(
        select(TradeExecution.executed_at, TradeExecution.fee_value).where(TradeExecution.user_id == user.id), f
    )
    for at, fv in db.execute(fee_stmt):
        if fv is not None:
            buckets[_period_key(at, tz, granularity)]["fees"] += fv
    return [
        {"period": k, "realized": _f(v["realized"]), "fees": _f(v["fees"]), "incomplete": v["incomplete"], "operations": v["operations"]}
        for k, v in sorted(buckets.items())
    ]


def equity_history(
    db: Session, user: User, start: datetime | None, end: datetime | None, connection_ids: list[uuid.UUID] | None = None
) -> list[dict]:
    """Patrimônio diário: último snapshot de cada conexão em cada dia (fuso do usuário)."""
    tz = ZoneInfo(user.timezone)
    stmt = select(BalanceSnapshot).where(BalanceSnapshot.user_id == user.id, BalanceSnapshot.base_currency == user.base_currency)
    if start:
        stmt = stmt.where(BalanceSnapshot.taken_at >= start)
    if end:
        stmt = stmt.where(BalanceSnapshot.taken_at <= end)
    if connection_ids:
        stmt = stmt.where(BalanceSnapshot.connection_id.in_(connection_ids))
    # dia -> conexão -> (taken_at, valor, completo)
    latest: dict[date, dict[uuid.UUID, tuple[datetime, Decimal, bool]]] = defaultdict(dict)
    batch: dict[tuple[uuid.UUID, datetime], list[BalanceSnapshot]] = defaultdict(list)
    for s in db.scalars(stmt.order_by(BalanceSnapshot.taken_at)):
        batch[(s.connection_id, s.taken_at)].append(s)
    for (cid, taken), snaps in batch.items():
        d = taken.astimezone(tz).date()
        value = sum((s.value or ZERO for s in snaps), ZERO)
        complete = all(s.value is not None for s in snaps)
        prev = latest[d].get(cid)
        if prev is None or prev[0] <= taken:
            latest[d][cid] = (taken, value, complete)
    out = []
    carry: dict[uuid.UUID, tuple[Decimal, bool]] = {}
    for d in sorted(latest):
        for cid, (_, v, c) in latest[d].items():
            carry[cid] = (v, c)
        out.append(
            {
                "date": d.isoformat(),
                "value": _f(sum((v for v, _ in carry.values()), ZERO)),
                "complete": all(c for _, c in carry.values()),
            }
        )
    return out


def recent_activity(db: Session, user: User, limit: int = 10) -> list[dict]:
    rows = db.scalars(
        select(TradeExecution).where(TradeExecution.user_id == user.id).order_by(TradeExecution.executed_at.desc()).limit(limit)
    )
    return [
        {
            "id": str(e.id),
            "executed_at": e.executed_at,
            "connection_name": e.connection.name,
            "symbol": e.symbol,
            "side": e.side,
            "quantity": _f(e.quantity),
            "price": _f(e.price),
            "quote_quantity": _f(e.quote_quantity),
            "quote_asset": e.quote_asset,
        }
        for e in rows
    ]
