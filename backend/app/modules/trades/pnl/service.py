"""Orquestra a apuração: lê o histórico do usuário, roda o motor e grava posições e resultados."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import bindparam, delete, select, update
from sqlalchemy.orm import Session

from app.integrations.base import PriceSource
from app.models import (
    AssetMovement,
    CycleStatus,
    ExchangeOrder,
    Position,
    RealizedPnlRecord,
    TradeCycle,
    TradeExecution,
    User,
)
from app.models.base import utcnow
from app.modules.trades.pnl.engine import EngineResult, LedgerMovement, LedgerTrade, compute
from app.modules.trades.pricing import HistoricalPrices

log = logging.getLogger("app.pnl")


def load_ledger(db: Session, user_id: uuid.UUID) -> tuple[list[LedgerTrade], list[LedgerMovement]]:
    trades = [
        LedgerTrade(
            id=e.id,
            connection_id=e.connection_id,
            at=e.executed_at,
            base=e.base_asset,
            quote=e.quote_asset,
            side=e.side,
            quantity=e.quantity,
            quote_quantity=e.quote_quantity,
            fee=e.fee,
            fee_asset=e.fee_asset,
        )
        for e in db.scalars(select(TradeExecution).where(TradeExecution.user_id == user_id))
    ]
    rows = db.scalars(
        select(AssetMovement).where(AssetMovement.user_id == user_id, AssetMovement.status == "completed")
    ).all()
    # Transferência entre contas próprias: mesmo tx_id em uma retirada e em um depósito do usuário.
    w_tx = {m.tx_id for m in rows if m.kind == "withdrawal" and m.tx_id}
    d_tx = {m.tx_id for m in rows if m.kind == "deposit" and m.tx_id}
    internal = w_tx & d_tx
    movements = [
        LedgerMovement(
            id=m.id,
            connection_id=m.connection_id,
            at=m.occurred_at,
            kind=m.kind,
            asset=m.asset,
            amount=m.amount,
            fee=m.fee,
            tx_id=m.tx_id,
            internal=m.tx_id in internal,
        )
        for m in rows
    ]
    return trades, movements


def recalculate_user(db: Session, user_id: uuid.UUID, price_source: PriceSource | None = None) -> EngineResult:
    user = db.get(User, user_id)
    assert user is not None
    trades, movements = load_ledger(db, user_id)
    prices = HistoricalPrices(db, user.base_currency, price_source)
    result = compute(trades, movements, base_currency=user.base_currency, method=user.cost_method, price=prices)

    now = utcnow()
    db.execute(delete(RealizedPnlRecord).where(RealizedPnlRecord.user_id == user_id))
    db.execute(delete(Position).where(Position.user_id == user_id))
    db.add_all(
        RealizedPnlRecord(
            user_id=user_id,
            connection_id=r.connection_id,
            execution_id=r.execution_id,
            kind=r.kind,
            asset=r.asset,
            base_currency=user.base_currency,
            method=user.cost_method,
            quantity=r.quantity,
            proceeds=r.proceeds,
            cost_basis=r.cost_basis,
            fees=r.fees,
            realized_pnl=r.realized_pnl,
            status=r.status,
            note=r.note,
            realized_at=r.at,
        )
        for r in result.realized
    )
    db.add_all(
        Position(
            user_id=user_id,
            asset=p.asset,
            base_currency=user.base_currency,
            method=user.cost_method,
            quantity=p.quantity,
            cost_basis=p.cost_basis,
            cost_basis_complete=p.complete,
            unknown_cost_quantity=p.unknown_qty,
            computed_at=now,
        )
        for p in result.positions.values()
    )
    if result.trade_fee_values:
        db.connection().execute(
            update(TradeExecution.__table__)
            .where(TradeExecution.__table__.c.id == bindparam("eid"))
            .values(fee_value=bindparam("fv"), fee_value_currency=bindparam("fc")),
            [{"eid": k, "fv": v, "fc": user.base_currency} for k, v in result.trade_fee_values.items()],
        )
    n_cycles = rebuild_cycles(db, user_id, price_source)
    db.commit()
    log.info(
        "pnl_recalculated",
        extra={
            "user_id": str(user_id),
            "records": len(result.realized),
            "cycles": n_cycles,
            "positions": len(result.positions),
            "prices_fetched": prices.fetched,
            "prices_missing": prices.missing,
        },
    )
    return result


OPEN_ORDER_STATUSES = ("NEW", "PARTIALLY_FILLED")


def rebuild_cycles(db: Session, user_id: uuid.UUID, price_source: PriceSource | None = None) -> int:
    """Recalcula as operações compra → venda do usuário. Não faz commit."""
    from app.modules.trades.cycles import Cycle, Exec, build_cycles

    execs = [
        Exec(
            id=e.id, connection_id=e.connection_id, at=e.executed_at, base=e.base_asset, quote=e.quote_asset,
            side=e.side, quantity=e.quantity, price=e.price, fee=e.fee, fee_asset=e.fee_asset, source=e.source,
        )
        for e in db.scalars(select(TradeExecution).where(TradeExecution.user_id == user_id))
    ]
    user = db.get(User, user_id)
    currency = user.base_currency if user else "BRL"
    fx = HistoricalPrices(db, currency, price_source)
    cycles = build_cycles(execs, fx, currency)

    # Ordens abertas na corretora: "Ordem Comprar" / "Ordem Vender".
    for o in db.scalars(select(ExchangeOrder).where(ExchangeOrder.user_id == user_id, ExchangeOrder.status.in_(OPEN_ORDER_STATUSES))):
        left = o.orig_qty - o.executed_qty
        if o.side == "BUY":
            cycles.append(Cycle(
                status=CycleStatus.BUY_ORDER, asset=o.base_asset, source="api", buy_connection_id=o.connection_id, buy_at=o.placed_at,
                buy_quote=o.quote_asset, buy_quantity=left, buy_price=o.price, buy_total=(left * o.price) if o.price else None,
            ))
        else:
            cycles.append(Cycle(
                status=CycleStatus.SELL_ORDER, asset=o.base_asset, source="api", sell_connection_id=o.connection_id, sell_order_id=o.id,
                sell_quote=o.quote_asset, sell_quantity=left, sell_price=o.price, sell_total=(left * o.price) if o.price else None,
                extra={"placed_at": o.placed_at},
            ))

    db.execute(delete(TradeCycle).where(TradeCycle.user_id == user_id))
    now = utcnow()
    rows = []
    for c in cycles:
        data = {k: v for k, v in c.__dict__.items() if k != "extra"}
        ref = c.sell_at if c.status == CycleStatus.CLOSED else (c.buy_at or c.extra.get("placed_at"))
        rows.append(TradeCycle(user_id=user_id, ref_at=ref, computed_at=now, **data))
    db.add_all(rows)
    return len(rows)
