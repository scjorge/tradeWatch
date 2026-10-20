"""Cotações: atuais (ticker) e históricas (kline de 1 minuto), sempre com fonte e horário registrados."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.integrations.base import PriceSource, TemporaryError
from app.models import AssetPrice
from app.models.base import utcnow

log = logging.getLogger("app.pricing")

TICKER = "binance:ticker"
KLINE = "binance:kline1m"
BRIDGE = "USDT"


@dataclass(frozen=True)
class Quote:
    price: Decimal
    source: str
    at: datetime


def _minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def _store(db: Session, rows: list[dict]) -> None:
    if rows:
        db.execute(insert(AssetPrice).values(rows).on_conflict_do_nothing(constraint="uq_asset_prices_point"))


def refresh_current_prices(db: Session, source: PriceSource, assets: set[str], base_currencies: set[str]) -> int:
    """Busca o ticker e guarda apenas os pares úteis para valorizar os ativos informados."""
    quotes = base_currencies | {BRIDGE}
    wanted = assets | quotes
    prices = source.current_prices(wanted)
    now = _minute(utcnow())
    rows = [
        {"base_asset": b, "quote_asset": q, "price": p, "source": TICKER, "price_at": now, "fetched_at": utcnow()}
        for (b, q), p in prices.items()
        if (b in wanted and q in quotes) or (q in wanted and b in quotes)
    ]
    _store(db, rows)
    db.commit()
    return len(rows)


class CurrentPrices:
    """Cotação mais recente por par, carregada do banco (sem chamadas externas)."""

    def __init__(self, db: Session):
        stmt = (
            select(AssetPrice)
            .where(AssetPrice.source == TICKER)
            .distinct(AssetPrice.base_asset, AssetPrice.quote_asset)
            .order_by(AssetPrice.base_asset, AssetPrice.quote_asset, AssetPrice.price_at.desc())
        )
        self._pairs: dict[tuple[str, str], Quote] = {
            (p.base_asset, p.quote_asset): Quote(p.price, p.source, p.price_at) for p in db.scalars(stmt)
        }

    def _direct(self, base: str, quote: str) -> Quote | None:
        if base == quote:
            return Quote(Decimal(1), "identity", utcnow())
        q = self._pairs.get((base, quote))
        if q:
            return q
        inv = self._pairs.get((quote, base))
        if inv and inv.price:
            return Quote(Decimal(1) / inv.price, inv.source + ":inverse", inv.at)
        return None

    def get(self, asset: str, base_currency: str) -> Quote | None:
        q = self._direct(asset, base_currency)
        if q:
            return q
        a, b = self._direct(asset, BRIDGE), self._direct(BRIDGE, base_currency)
        if a and b:
            return Quote(a.price * b.price, f"{a.source}+bridge:{BRIDGE}", min(a.at, b.at))
        return None


class HistoricalPrices:
    """Cotação no minuto da operação. Usa cache no banco e, opcionalmente, a fonte externa.

    ``budget`` limita chamadas externas por execução; o que faltar fica "incompleto"
    até a próxima apuração.
    """

    def __init__(self, db: Session, base_currency: str, source: PriceSource | None = None, budget: int = 400):
        self.db = db
        self.r = base_currency
        self.source = source
        self.budget = budget
        self._memo: dict[tuple[str, str, datetime], Decimal | None] = {}
        self.fetched = 0
        self.missing = 0

    def _pair(self, base: str, quote: str, minute: datetime) -> Decimal | None:
        if base == quote:
            return Decimal(1)
        key = (base, quote, minute)
        if key in self._memo:
            return self._memo[key]
        cached = self.db.scalar(
            select(AssetPrice.price).where(
                AssetPrice.base_asset == base,
                AssetPrice.quote_asset == quote,
                AssetPrice.source == KLINE,
                AssetPrice.price_at == minute,
            )
        )
        price = cached
        if price is None and self.source is not None and self.budget > 0:
            self.budget -= 1
            try:
                price = self.source.historical_price(base, quote, minute)
            except TemporaryError as exc:
                log.warning("historical_price_unavailable", extra={"pair": f"{base}/{quote}", "error": str(exc)})
                price = None
            if price is not None:
                self.fetched += 1
                _store(
                    self.db,
                    [{"base_asset": base, "quote_asset": quote, "price": price, "source": KLINE, "price_at": minute, "fetched_at": utcnow()}],
                )
        self._memo[key] = price
        return price

    def __call__(self, asset: str, at: datetime) -> Decimal | None:
        minute = _minute(at)
        p = self._pair(asset, self.r, minute)
        if p is None and BRIDGE not in (asset, self.r):
            a = self._pair(asset, BRIDGE, minute)
            b = self._pair(BRIDGE, self.r, minute) if a is not None else None
            p = a * b if a is not None and b is not None else None
        if p is None:
            self.missing += 1
        return p
