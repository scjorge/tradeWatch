"""Operações compra → venda (cada compra casada com a venda que a encerrou), com filtros de resultado."""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.db import get_db
from app.models import CycleStatus, TradeCycle, User
from app.models.base import utcnow
from app.modules.trades.filters import Filters, filters_dep
from app.modules.trades.pricing import CurrentPrices

router = APIRouter(prefix="/api/trades", tags=["operations"])
READ = "trades:read"
ZERO = Decimal(0)
STATUS_LABELS = {
    CycleStatus.BUY_ORDER: "Ordem Comprar",
    CycleStatus.OPEN: "Ativo",
    CycleStatus.SELL_ORDER: "Ordem Vender",
    CycleStatus.CLOSED: "Concluído",
}


def _f(v: Decimal | None) -> str | None:
    return None if v is None else format(Decimal(v).normalize(), "f")


# ------------------------------------------------------------------ filtros
@dataclass
class CycleFilters:
    status: list[str] | None
    quote: str | None
    result: str | None
    min_pnl: Decimal | None
    max_pnl: Decimal | None
    min_pct: Decimal | None
    max_pct: Decimal | None
    min_days: Decimal | None
    max_days: Decimal | None

    @property
    def result_only_closed(self) -> bool:
        return any(v is not None for v in (self.result, self.min_pnl, self.max_pnl, self.min_pct, self.max_pct, self.min_days, self.max_days))


def cycle_filters(
    status: list[str] | None = Query(None, description="buy_order | open | sell_order | closed"),
    quote: str | None = Query(None, max_length=10),
    result: str | None = Query(None, pattern="^(gain|loss|even|incomplete)$"),
    min_pnl: Decimal | None = None,
    max_pnl: Decimal | None = None,
    min_pct: Decimal | None = None,
    max_pct: Decimal | None = None,
    min_days: Decimal | None = Query(None, ge=0),
    max_days: Decimal | None = Query(None, ge=0),
) -> CycleFilters:
    return CycleFilters(status, quote.upper() if quote else None, result, min_pnl, max_pnl, min_pct, max_pct, min_days, max_days)


def _query(user: User, f: Filters, cf: CycleFilters):
    C = TradeCycle
    stmt = select(C).where(C.user_id == user.id)
    if f.start:
        stmt = stmt.where(C.ref_at >= f.start)
    if f.end:
        stmt = stmt.where(C.ref_at <= f.end)
    if f.connection_ids:
        stmt = stmt.where(or_(C.buy_connection_id.in_(f.connection_ids), C.sell_connection_id.in_(f.connection_ids)))
    if f.asset:
        stmt = stmt.where(C.asset == f.asset)
    if f.q:
        stmt = stmt.where(C.asset.ilike(f"%{f.q.strip()}%"))
    if cf.status:
        stmt = stmt.where(C.status.in_(cf.status))
    if cf.quote:
        stmt = stmt.where(or_(C.buy_quote == cf.quote, C.sell_quote == cf.quote))
    if cf.result_only_closed:
        stmt = stmt.where(C.status == CycleStatus.CLOSED)
    if cf.result == "gain":
        stmt = stmt.where(C.pnl_brl > 0)
    elif cf.result == "loss":
        stmt = stmt.where(C.pnl_brl < 0)
    elif cf.result == "even":
        stmt = stmt.where(C.pnl_brl == 0)
    elif cf.result == "incomplete":
        stmt = stmt.where(C.complete.is_(False))
    for col, lo, hi in ((C.pnl_brl, cf.min_pnl, cf.max_pnl), (C.pnl_pct, cf.min_pct, cf.max_pct), (C.holding_days, cf.min_days, cf.max_days)):
        if lo is not None:
            stmt = stmt.where(col >= lo)
        if hi is not None:
            stmt = stmt.where(col <= hi)
    return stmt


# ------------------------------------------------------------------ valores (inclui estimativa de posições abertas)
def _live(c: TradeCycle, prices: CurrentPrices, ref: str = "BRL") -> dict:
    """Para "Ativo"/"Ordem Vender": estima a venda pela cotação atual ou pelo preço-alvo."""
    est = {"estimated": False, "price_source": None}
    if c.status not in (CycleStatus.OPEN, CycleStatus.SELL_ORDER) or c.buy_total_brl is None or not c.sell_quantity:
        return est
    quote = c.buy_quote or c.sell_quote
    price, source = c.sell_price, "preço-alvo da ordem"
    if c.status == CycleStatus.OPEN or price is None:
        q = prices.get(c.asset, quote)
        price, source = (q.price, q.source) if q else (None, None)
    # Câmbio atual; sem cotação recente, usa o câmbio da compra.
    cur = None if quote == ref else prices.get(quote, ref)
    fxq = Decimal(1) if quote == ref else (cur.price if cur else c.buy_fx)
    if price is None or fxq is None:
        return {**est, "estimated": True}
    total = c.sell_quantity * price
    total_brl = total * fxq
    pnl = total_brl - c.buy_total_brl
    return {
        "estimated": True,
        "price_source": source,
        "sell_price": price,
        "sell_fx": fxq,
        "sell_total": total,
        "sell_total_brl": total_brl,
        "pnl_brl": pnl,
        "pnl_pct": pnl / c.buy_total_brl * 100 if c.buy_total_brl else None,
    }


def _out(c: TradeCycle, prices: CurrentPrices, names: dict, ref: str = "BRL") -> dict:
    live = _live(c, prices, ref)
    v = lambda k: live.get(k, getattr(c, k))  # noqa: E731
    sell_qty = c.sell_quantity
    return {
        "id": str(c.id),
        "status": c.status,
        "status_label": STATUS_LABELS[c.status],
        "asset": c.asset,
        "quote": c.buy_quote or c.sell_quote,
        "sell_quote": c.sell_quote,
        "complete": c.complete,
        "note": c.note,
        "source": c.source,
        "account": names.get(c.buy_connection_id) or names.get(c.sell_connection_id),
        "buy_at": c.buy_at,
        "buy_quantity": _f(c.buy_quantity),
        "buy_price": _f(c.buy_price),
        "buy_fee": _f(c.buy_fee),
        "buy_fee_asset": c.buy_fee_asset,
        "buy_unit_brl": _f(c.buy_price * c.buy_fx) if c.buy_price is not None and c.buy_fx is not None else None,
        "buy_total": _f(c.buy_total),
        "buy_fx": _f(c.buy_fx),
        "buy_total_brl": _f(c.buy_total_brl),
        "sell_at": c.sell_at,
        "sell_quantity": _f(sell_qty),
        "sell_price": _f(v("sell_price")),
        "sell_fee": _f(c.sell_fee),
        "sell_fee_asset": c.sell_fee_asset,
        "sell_unit_brl": _f(v("sell_price") * v("sell_fx")) if v("sell_price") is not None and v("sell_fx") is not None else None,
        "sell_total": _f(v("sell_total")),
        "sell_fx": _f(v("sell_fx")),
        "sell_total_brl": _f(v("sell_total_brl")),
        "pnl_brl": _f(v("pnl_brl")),
        "pnl_pct": float(v("pnl_pct")) if v("pnl_pct") is not None else None,
        "pnl_quote": _f(c.pnl_quote),
        "fx_effect_brl": _f(c.fx_effect_brl),
        "fees_brl": _f(c.fees_brl),
        "holding_days": float(c.holding_days) if c.holding_days is not None else (
            (utcnow() - c.buy_at).total_seconds() / 86400 if c.buy_at and c.status in (CycleStatus.OPEN, CycleStatus.SELL_ORDER) else None
        ),
        "estimated": live["estimated"],
        "price_source": live["price_source"],
    }


def _names(db: Session, user: User) -> dict:
    from app.models import ExchangeConnection

    return {c.id: c.name for c in db.scalars(select(ExchangeConnection).where(ExchangeConnection.user_id == user.id))}


SORTS = {
    "ref_at": TradeCycle.ref_at,
    "buy_at": TradeCycle.buy_at,
    "sell_at": TradeCycle.sell_at,
    "asset": TradeCycle.asset,
    "status": TradeCycle.status,
    "pnl_brl": TradeCycle.pnl_brl,
    "pnl_pct": TradeCycle.pnl_pct,
    "buy_total_brl": TradeCycle.buy_total_brl,
    "holding_days": TradeCycle.holding_days,
}


@router.get("/cycles")
def list_cycles(
    f: Filters = Depends(filters_dep),
    cf: CycleFilters = Depends(cycle_filters),
    sort: str = Query("ref_at"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    stmt = _query(user, f, cf)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    col = SORTS.get(sort, TradeCycle.ref_at)
    order = col.desc().nulls_last() if direction == "desc" else col.asc().nulls_last()
    rows = db.scalars(stmt.order_by(order, TradeCycle.id).offset((page - 1) * page_size).limit(page_size)).all()
    prices, names = CurrentPrices(db), _names(db, user)
    items = [_out(c, prices, names, user.base_currency) for c in rows]
    return {"total": total, "page": page, "page_size": page_size, "currency": user.base_currency, "items": items}


# ------------------------------------------------------------------ resumo e análises
def _period(d: datetime, tz: ZoneInfo, g: str) -> str:
    x = d.astimezone(tz).date()
    if g == "year":
        return str(x.year)
    if g == "month":
        return x.strftime("%Y-%m")
    if g == "week":
        return (x - timedelta(days=x.weekday())).isoformat()
    return x.isoformat()


@router.get("/cycles/summary")
def cycles_summary(
    f: Filters = Depends(filters_dep),
    cf: CycleFilters = Depends(cycle_filters),
    granularity: str = Query("month", pattern="^(day|week|month|year)$"),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    tz = ZoneInfo(user.timezone)
    rows = db.scalars(_query(user, f, cf)).all()
    prices = CurrentPrices(db)
    closed = [c for c in rows if c.status == CycleStatus.CLOSED and c.pnl_brl is not None]
    wins = [c.pnl_brl for c in closed if c.pnl_brl > 0]
    losses = [c.pnl_brl for c in closed if c.pnl_brl < 0]
    gains, loss_abs = sum(wins, ZERO), -sum(losses, ZERO)
    invested = sum((c.buy_total_brl or ZERO for c in closed), ZERO)
    pnl = sum((c.pnl_brl for c in closed), ZERO)
    holding = [c.holding_days for c in closed if c.holding_days is not None]

    open_rows = [c for c in rows if c.status in (CycleStatus.OPEN, CycleStatus.SELL_ORDER)]
    live = [(c, _live(c, prices, user.base_currency)) for c in open_rows if c.status == CycleStatus.OPEN]
    unrealized = [x["pnl_brl"] for _, x in live if x.get("pnl_brl") is not None]

    def rec(c):
        return None if c is None else {"id": str(c.id), "asset": c.asset, "pnl_brl": _f(c.pnl_brl), "pnl_pct": float(c.pnl_pct) if c.pnl_pct is not None else None, "sell_at": c.sell_at}

    buckets: dict[str, dict] = defaultdict(lambda: {"pnl": ZERO, "count": 0, "wins": 0, "invested": ZERO, "fees": ZERO, "gains": ZERO, "losses": ZERO})
    for c in closed:
        b = buckets[_period(c.sell_at, tz, granularity)]
        b["pnl"] += c.pnl_brl
        b["count"] += 1
        b["wins"] += 1 if c.pnl_brl > 0 else 0
        b["gains"] += c.pnl_brl if c.pnl_brl > 0 else ZERO
        b["losses"] += c.pnl_brl if c.pnl_brl < 0 else ZERO
        b["invested"] += c.buy_total_brl or ZERO
        b["fees"] += c.fees_brl or ZERO
    periods, cumulative, prev = [], ZERO, None
    for k in sorted(buckets):
        b = buckets[k]
        cumulative += b["pnl"]
        periods.append(
            {
                "period": k,
                "pnl_brl": _f(b["pnl"]),
                "gains_brl": _f(b["gains"]),
                "losses_brl": _f(b["losses"]),
                "cumulative_brl": _f(cumulative),
                "count": b["count"],
                "win_rate_pct": b["wins"] / b["count"] * 100,
                "return_pct": float(b["pnl"] / b["invested"] * 100) if b["invested"] else None,
                "invested_brl": _f(b["invested"]),
                "fees_brl": _f(b["fees"]),
                "change_vs_prev_brl": _f(b["pnl"] - prev) if prev is not None else None,
            }
        )
        prev = b["pnl"]

    assets: dict[str, dict] = defaultdict(lambda: {"pnl": ZERO, "count": 0, "wins": 0, "invested": ZERO})
    for c in closed:
        a = assets[c.asset]
        a["pnl"] += c.pnl_brl
        a["count"] += 1
        a["wins"] += 1 if c.pnl_brl > 0 else 0
        a["invested"] += c.buy_total_brl or ZERO
    by_asset = sorted(
        (
            {"asset": k, "pnl_brl": _f(v["pnl"]), "count": v["count"], "win_rate_pct": v["wins"] / v["count"] * 100,
             "return_pct": float(v["pnl"] / v["invested"] * 100) if v["invested"] else None}
            for k, v in assets.items()
        ),
        key=lambda x: Decimal(x["pnl_brl"]),
        reverse=True,
    )

    return {
        "currency": user.base_currency,
        "granularity": granularity,
        "closed_count": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(closed) * 100 if closed else None,
        "pnl_brl": _f(pnl),
        "gains_brl": _f(gains),
        "losses_brl": _f(-loss_abs),
        "invested_closed_brl": _f(invested),
        "return_pct": float(pnl / invested * 100) if invested else None,
        "fees_brl": _f(sum((c.fees_brl or ZERO for c in closed), ZERO)),
        "fx_effect_brl": _f(sum((c.fx_effect_brl or ZERO for c in closed), ZERO)),
        "avg_gain_brl": _f(gains / len(wins)) if wins else None,
        "avg_loss_brl": _f(-loss_abs / len(losses)) if losses else None,
        "payoff_ratio": float((gains / len(wins)) / (loss_abs / len(losses))) if wins and losses else None,
        "profit_factor": float(gains / loss_abs) if loss_abs else None,
        "avg_holding_days": float(sum(holding, ZERO) / len(holding)) if holding else None,
        "best": rec(max(closed, key=lambda c: c.pnl_brl, default=None)),
        "worst": rec(min(closed, key=lambda c: c.pnl_brl, default=None)),
        "incomplete_count": len([c for c in rows if not c.complete]),
        "open_count": len(open_rows),
        "open_invested_brl": _f(sum((c.buy_total_brl or ZERO for c in open_rows), ZERO)),
        "unrealized_brl": _f(sum(unrealized, ZERO)),
        "unrealized_complete": len(unrealized) == len(live),
        "pending_orders": len([c for c in rows if c.status in (CycleStatus.BUY_ORDER, CycleStatus.SELL_ORDER)]),
        "periods": periods,
        "by_asset": by_asset,
    }


@router.get("/cycles/calendar")
def cycles_calendar(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    f: Filters = Depends(filters_dep),
    cf: CycleFilters = Depends(cycle_filters),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    """Resultado por dia de venda no mês."""
    tz = ZoneInfo(user.timezone)
    first = date.fromisoformat(month + "-01")
    nxt = (first + timedelta(days=32)).replace(day=1)
    f.start = datetime.combine(first, datetime.min.time(), tzinfo=tz)
    f.end = datetime.combine(nxt, datetime.min.time(), tzinfo=tz) - timedelta(microseconds=1)
    cf.status = [CycleStatus.CLOSED]
    days = {first + timedelta(days=i): {"pnl": ZERO, "count": 0} for i in range((nxt - first).days)}
    for c in db.scalars(_query(user, f, cf)):
        if c.pnl_brl is None:
            continue
        d = c.sell_at.astimezone(tz).date()
        if d in days:
            days[d]["pnl"] += c.pnl_brl
            days[d]["count"] += 1
    total = sum((v["pnl"] for v in days.values()), ZERO)
    return {"month": month, "total_brl": _f(total), "days": [{"date": d, "pnl_brl": _f(v["pnl"]), "count": v["count"]} for d, v in days.items()]}


# ------------------------------------------------------------------ compra e venda consolidada
DEC_FIELDS = (
    "buy_quantity", "buy_price", "buy_fee", "buy_unit_brl", "buy_total", "buy_fx", "buy_total_brl",
    "sell_quantity", "sell_price", "sell_fee", "sell_unit_brl", "sell_total", "sell_fx", "sell_total_brl",
    "pnl_brl", "pnl_quote", "fx_effect_brl", "fees_brl",
)
FLOAT_FIELDS = ("pnl_pct", "holding_days")
POST_FILTERS = ("result", "min_pnl", "max_pnl", "min_pct", "max_pct", "min_days", "max_days")


def _order_keys(db: Session, user: User) -> dict:
    """execução → identificador da ordem (id interno, senão o ID externo da corretora, senão a própria execução)."""
    from app.models import TradeExecution as E

    keys = {}
    for eid, oid, ext, conn in db.execute(select(E.id, E.order_id, E.external_order_id, E.connection_id).where(E.user_id == user.id)):
        keys[eid] = ("o", oid) if oid else (("x", conn, ext) if ext else ("e", eid))
    return keys


def _group_key(c: TradeCycle, orders: dict):
    def k(eid):
        return None if eid is None else orders.get(eid, ("e", eid))

    if c.status == CycleStatus.CLOSED:
        sell = k(c.sell_execution_id) if c.sell_execution_id else ("so", c.sell_order_id)
        return ("closed", c.asset, c.buy_quote, c.sell_quote, k(c.buy_execution_id), sell)
    if c.status == CycleStatus.OPEN and c.buy_execution_id:
        return ("open", c.asset, c.buy_quote, k(c.buy_execution_id))
    return ("row", c.id)  # ordens abertas já são uma linha por ordem


def _raw(c: TradeCycle, prices: CurrentPrices, names: dict, ref: str = "BRL") -> dict:
    d = _out(c, prices, names, ref)
    for k in DEC_FIELDS:
        d[k] = None if d[k] is None else Decimal(d[k])
    for k in FLOAT_FIELDS:
        d[k] = None if d[k] is None else Decimal(str(d[k]))
    d["buy_execution_id"], d["sell_execution_id"], d["ref_at"] = c.buy_execution_id, c.sell_execution_id, c.ref_at
    return d


def _passes(r: dict, cf: CycleFilters) -> bool:
    pnl, pct, days = r["pnl_brl"], r["pnl_pct"], r["holding_days"]
    if cf.result == "gain" and not (pnl is not None and pnl > 0):
        return False
    if cf.result == "loss" and not (pnl is not None and pnl < 0):
        return False
    if cf.result == "even" and pnl != 0:
        return False
    if cf.result == "incomplete" and r["complete"]:
        return False
    for v, lo, hi in ((pnl, cf.min_pnl, cf.max_pnl), (pct, cf.min_pct, cf.max_pct), (days, cf.min_days, cf.max_days)):
        if (lo is not None or hi is not None) and v is None:
            return False
        if lo is not None and v < lo:
            return False
        if hi is not None and v > hi:
            return False
    return True


def _consolidated(db: Session, user: User, f: Filters, cf: CycleFilters) -> list[dict]:
    from dataclasses import replace

    from app.modules.trades.consolidated import consolidate

    # Filtros de resultado valem para a linha consolidada, não para cada pedaço.
    base = replace(cf, **{k: None for k in POST_FILTERS})
    if cf.result_only_closed:
        base.status = [s for s in (cf.status or [CycleStatus.CLOSED]) if s == CycleStatus.CLOSED] or ["-"]
    prices, names, orders = CurrentPrices(db), _names(db, user), _order_keys(db, user)
    rows = db.scalars(_query(user, f, base).order_by(TradeCycle.ref_at.desc().nulls_last(), TradeCycle.id))
    merged = consolidate((_group_key(c, orders), _raw(c, prices, names, user.base_currency)) for c in rows)
    for r in merged:
        r["id"] = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{user.id}:{r['id']}"))
    return [r for r in merged if _passes(r, cf)]


def _fmt(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k not in ("buy_execution_id", "sell_execution_id", "ref_at")}
    for k in DEC_FIELDS:
        out[k] = _f(r[k])
    for k in FLOAT_FIELDS:
        out[k] = None if r[k] is None else float(r[k])
    return out


CONSOLIDATED_SORTS = {"ref_at", "buy_at", "sell_at", "asset", "status", "pnl_brl", "pnl_pct", "buy_total_brl", "holding_days"}


@router.get("/cycles/consolidated")
def list_cycles_consolidated(
    f: Filters = Depends(filters_dep),
    cf: CycleFilters = Depends(cycle_filters),
    sort: str = Query("ref_at"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    """Mesma tabela de compra e venda, com as execuções da mesma ordem somadas numa linha só."""
    rows = _consolidated(db, user, f, cf)
    key = sort if sort in CONSOLIDATED_SORTS else "ref_at"
    filled = sorted((r for r in rows if r[key] is not None), key=lambda r: r[key], reverse=direction == "desc")
    rows = filled + [r for r in rows if r[key] is None]  # vazios sempre no fim
    start = (page - 1) * page_size
    items = [_fmt(r) for r in rows[start:start + page_size]]
    return {"total": len(rows), "page": page, "page_size": page_size, "currency": user.base_currency, "items": items}


def _header(h: str, user: User) -> str:
    """Colunas em moeda de referência levam o código da moeda escolhida pelo usuário."""
    return h.replace("BRL", user.base_currency)


EXPORT_COLUMNS = [
    ("Status", "status_label"), ("Criptomoeda", "asset"), ("Moeda", "quote"), ("Conta", "account"), ("Data da Compra", "buy_at"),
    ("Quant. a Comprar", "buy_quantity"), ("Valor Unitário Compra", "buy_price"), ("Taxa Transação", "buy_fee"),
    ("Câmbio Compra", "buy_fx"), ("Valor Unitário Compra BRL", "buy_unit_brl"), ("Valor Total da Compra", "buy_total"),
    ("Valor Compra BRL", "buy_total_brl"), ("Data da Venda.", "sell_at"), ("Quant. a Vender", "sell_quantity"),
    ("Valor Unitário Venda", "sell_price"), ("Taxa Venda", "sell_fee"), ("Taxa BRL", "fees_brl"), ("Câmbio Venda", "sell_fx"),
    ("Valor Unitário Venda BRL", "sell_unit_brl"), ("Valor Total a Venda", "sell_total"), ("Valor Venda BRL", "sell_total_brl"),
    ("Lucro / Prejuízo", "pnl_brl"), ("% Lucro / Prejuízo", "pnl_pct"), ("Dias", "holding_days"), ("Observação", "note"),
]


@router.get("/cycles.csv")
def export_cycles(
    f: Filters = Depends(filters_dep),
    cf: CycleFilters = Depends(cycle_filters),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    from app.modules.trades.router_data import _csv_safe

    tz = ZoneInfo(user.timezone)
    prices, names = CurrentPrices(db), _names(db, user)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([_header(h, user) for h, _ in EXPORT_COLUMNS])
    for c in db.scalars(_query(user, f, cf).order_by(TradeCycle.ref_at.desc().nulls_last()).limit(100_000)):
        d = _out(c, prices, names, user.base_currency)
        if d["estimated"]:
            for k in ("sell_price", "sell_fx", "sell_unit_brl", "sell_total", "sell_total_brl", "pnl_brl", "pnl_pct"):
                d[k] = None  # estimativas não são exportadas como se fossem realizadas
        for k in ("buy_at", "sell_at"):
            d[k] = d[k].astimezone(tz).strftime("%d/%m/%Y") if d[k] else None
        w.writerow([_csv_safe(d[k]) for _, k in EXPORT_COLUMNS])
    name = f"operacoes-compra-venda-{utcnow():%Y%m%d}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


CONSOLIDATED_EXPORT_COLUMNS = EXPORT_COLUMNS[:4] + [("Execuções Compra", "buy_executions"), ("Execuções Venda", "sell_executions")] + EXPORT_COLUMNS[4:]


@router.get("/cycles/consolidated.csv")
def export_cycles_consolidated(
    f: Filters = Depends(filters_dep),
    cf: CycleFilters = Depends(cycle_filters),
    user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
):
    from app.modules.trades.router_data import _csv_safe

    tz = ZoneInfo(user.timezone)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([_header(h, user) for h, _ in CONSOLIDATED_EXPORT_COLUMNS])
    for r in _consolidated(db, user, f, cf)[:100_000]:
        d = _fmt(r)
        if d["estimated"]:
            for k in ("sell_price", "sell_fx", "sell_unit_brl", "sell_total", "sell_total_brl", "pnl_brl", "pnl_pct"):
                d[k] = None  # estimativas não são exportadas como se fossem realizadas
        for k in ("buy_at", "sell_at"):
            d[k] = d[k].astimezone(tz).strftime("%d/%m/%Y") if d[k] else None
        w.writerow([_csv_safe(d[k]) for _, k in CONSOLIDATED_EXPORT_COLUMNS])
    name = f"operacoes-compra-venda-consolidada-{utcnow():%Y%m%d}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/refresh-prices")
def refresh_prices(user: User = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    """Atualiza cotações dos ativos em aberto (para estimar posições "Ativo")."""
    from app.core.errors import AppError
    from app.integrations.registry import build_price_source
    from app.modules.trades.pricing import refresh_current_prices

    rows = db.execute(
        select(TradeCycle.asset, TradeCycle.buy_quote).where(TradeCycle.user_id == user.id, TradeCycle.status.in_((CycleStatus.OPEN, CycleStatus.SELL_ORDER))).distinct()
    ).all()
    assets = {a for a, _ in rows} | {"USDT"}
    quotes = {q for _, q in rows if q} | {"BRL", "USDT"}
    source = build_price_source()
    try:
        n = refresh_current_prices(db, source, assets | quotes, quotes)
    except Exception:  # noqa: BLE001
        db.rollback()
        raise AppError("Não foi possível consultar as cotações agora. Tente novamente em instantes.", code="prices_unavailable") from None
    finally:
        if hasattr(source, "close"):
            source.close()
    return {"pairs": n}
