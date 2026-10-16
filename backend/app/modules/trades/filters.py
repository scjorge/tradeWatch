from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from fastapi import Query
from sqlalchemy import or_, select

from app.models import ExchangeConnection, ExchangeProvider, RealizedPnlRecord, TradeExecution


@dataclass
class Filters:
    start: datetime | None = None
    end: datetime | None = None
    connection_ids: list[uuid.UUID] | None = None
    provider: str | None = None
    asset: str | None = None
    symbol: str | None = None
    market: str | None = None
    side: str | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    q: str | None = None


def filters_dep(
    start: datetime | None = Query(None, description="Início (ISO 8601, UTC)"),
    end: datetime | None = Query(None, description="Fim (ISO 8601, UTC)"),
    connection_id: list[uuid.UUID] | None = Query(None),
    provider: str | None = Query(None, max_length=40),
    asset: str | None = Query(None, max_length=20),
    symbol: str | None = Query(None, max_length=40),
    market: str | None = Query(None, max_length=20),
    side: str | None = Query(None, pattern="^(BUY|SELL)$"),
    min_value: Decimal | None = Query(None, ge=0),
    max_value: Decimal | None = Query(None, ge=0),
    q: str | None = Query(None, max_length=80),
) -> Filters:
    return Filters(
        start, end, connection_id, provider, asset.upper() if asset else None,
        symbol.upper() if symbol else None, market, side, min_value, max_value, q,
    )


def apply_execution_filters(stmt, f: Filters):
    E = TradeExecution
    if f.start:
        stmt = stmt.where(E.executed_at >= f.start)
    if f.end:
        stmt = stmt.where(E.executed_at <= f.end)
    if f.connection_ids:
        stmt = stmt.where(E.connection_id.in_(f.connection_ids))
    if f.provider:
        stmt = stmt.where(
            E.connection_id.in_(
                select(ExchangeConnection.id)
                .join(ExchangeProvider, ExchangeConnection.provider_id == ExchangeProvider.id)
                .where(ExchangeProvider.key == f.provider)
            )
        )
    if f.asset:
        stmt = stmt.where(or_(E.base_asset == f.asset, E.quote_asset == f.asset))
    if f.symbol:
        stmt = stmt.where(E.symbol == f.symbol)
    if f.market:
        stmt = stmt.where(E.market == f.market)
    if f.side:
        stmt = stmt.where(E.side == f.side)
    if f.min_value is not None:
        stmt = stmt.where(E.quote_quantity >= f.min_value)
    if f.max_value is not None:
        stmt = stmt.where(E.quote_quantity <= f.max_value)
    if f.q:
        like = f"%{f.q.strip()}%"
        stmt = stmt.where(or_(E.symbol.ilike(like), E.external_id.ilike(like), E.external_order_id.ilike(like)))
    return stmt


def apply_realized_filters(stmt, f: Filters):
    R = RealizedPnlRecord
    if f.start:
        stmt = stmt.where(R.realized_at >= f.start)
    if f.end:
        stmt = stmt.where(R.realized_at <= f.end)
    if f.connection_ids:
        stmt = stmt.where(R.connection_id.in_(f.connection_ids))
    if f.asset:
        stmt = stmt.where(R.asset == f.asset)
    if f.symbol or f.side or f.market or f.provider:
        sub = apply_execution_filters(
            select(TradeExecution.id),
            Filters(symbol=f.symbol, side=f.side, market=f.market, provider=f.provider),
        )
        stmt = stmt.where(R.execution_id.in_(sub))
    return stmt
