"""Operações compra → venda (função pura).

Cada compra vira um lote do ativo. Cada venda consome os lotes mais antigos do
mesmo ativo (FIFO, todas as contas do usuário). Cada pedaço (lote × venda) vira
uma linha:

  Valor Total da Compra = quantidade × valor unitário          (moeda de cotação)
  Valor Compra BRL      = total × câmbio da compra (+ taxa paga em outro ativo)
  Quant. a Vender       = quantidade − taxa (taxa cobrada no próprio ativo)
  Valor Total a Venda   = valor unitário de venda × quantidade − taxa da venda
  Valor Venda BRL       = total da venda × câmbio da venda
  Lucro / Prejuízo      = Venda BRL − Compra BRL ;  % = Lucro ÷ Compra BRL

Câmbio = cotação histórica do minuto de cada execução. Sem câmbio ou sem compra
correspondente, a linha fica marcada como incompleta e sem lucro calculado.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

ZERO = Decimal(0)
EPS = Decimal("1e-12")
BRL = "BRL"

BrlFn = Callable[[str, datetime], Decimal | None]


@dataclass(frozen=True)
class Exec:
    id: uuid.UUID | None
    connection_id: uuid.UUID | None
    at: datetime
    base: str
    quote: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_asset: str | None
    source: str | None = None


@dataclass
class _Lot:
    ex: Exec
    gross: Decimal  # quantidade comprada (coluna "Quant. a Comprar")
    net: Decimal  # quantidade recebida (compra − taxa no ativo)
    remaining: Decimal
    fee_qty: Decimal  # taxa na moeda informada pela corretora
    fee_asset: str | None
    fx: Decimal | None
    cost_brl: Decimal | None  # custo total do lote em BRL (inclui taxa paga em outro ativo)
    cost_quote: Decimal  # custo total na moeda de cotação (taxa em outro ativo não entra)
    fee_brl: Decimal | None  # valor da taxa da compra em BRL


@dataclass
class Cycle:
    status: str
    asset: str
    complete: bool = True
    note: str | None = None
    source: str | None = None
    buy_execution_id: uuid.UUID | None = None
    buy_connection_id: uuid.UUID | None = None
    buy_at: datetime | None = None
    buy_quote: str | None = None
    buy_quantity: Decimal | None = None
    buy_price: Decimal | None = None
    buy_fee: Decimal | None = None
    buy_fee_asset: str | None = None
    buy_total: Decimal | None = None
    buy_fx: Decimal | None = None
    buy_total_brl: Decimal | None = None
    sell_execution_id: uuid.UUID | None = None
    sell_connection_id: uuid.UUID | None = None
    sell_order_id: uuid.UUID | None = None
    sell_at: datetime | None = None
    sell_quote: str | None = None
    sell_quantity: Decimal | None = None
    sell_price: Decimal | None = None
    sell_fee: Decimal | None = None
    sell_fee_asset: str | None = None
    sell_total: Decimal | None = None
    sell_fx: Decimal | None = None
    sell_total_brl: Decimal | None = None
    pnl_brl: Decimal | None = None
    pnl_pct: Decimal | None = None
    pnl_quote: Decimal | None = None
    fx_effect_brl: Decimal | None = None
    fees_brl: Decimal | None = None
    holding_days: Decimal | None = None
    extra: dict = field(default_factory=dict)


def _fx(ex: Exec, quote: str, brl: BrlFn) -> Decimal | None:
    if quote == BRL:
        return Decimal(1)
    return brl(quote, ex.at)


def _value_brl(asset: str | None, qty: Decimal, ex: Exec, brl: BrlFn) -> Decimal | None:
    if not qty:
        return ZERO
    if asset is None:
        return None
    if asset == BRL:
        return qty
    if asset == ex.quote:
        fx = _fx(ex, ex.quote, brl)
        return None if fx is None else qty * fx
    if asset == ex.base:
        fx = _fx(ex, ex.quote, brl)
        return None if fx is None else qty * ex.price * fx
    p = brl(asset, ex.at)
    return None if p is None else qty * p


def build_cycles(execs: list[Exec], brl: BrlFn) -> list[Cycle]:
    lots: dict[str, deque[_Lot]] = defaultdict(deque)
    out: list[Cycle] = []

    for ex in sorted(execs, key=lambda e: (e.at, 0 if e.side == "BUY" else 1)):
        if ex.quantity <= 0:
            continue
        fee = ex.fee or ZERO
        if ex.side == "BUY":
            fx = _fx(ex, ex.quote, brl)
            gross = ex.quantity
            net = gross - fee if ex.fee_asset == ex.base else gross
            cost_quote = gross * ex.price + (fee if ex.fee_asset == ex.quote else ZERO)
            cost_brl = None if fx is None else cost_quote * fx
            if cost_brl is not None and fee and ex.fee_asset not in (ex.base, ex.quote):
                fee_brl = _value_brl(ex.fee_asset, fee, ex, brl)
                cost_brl = None if fee_brl is None else cost_brl + fee_brl
            fee_brl = _value_brl(ex.fee_asset, fee, ex, brl) if fee else ZERO
            lots[ex.base].append(_Lot(ex, gross, net, net, fee, ex.fee_asset, fx, cost_brl, cost_quote, fee_brl))
            continue

        # Venda: consome lotes FIFO do ativo.
        sold = ex.quantity + (fee if ex.fee_asset == ex.base else ZERO)
        sell_fx = _fx(ex, ex.quote, brl)
        proceeds_quote = ex.quantity * ex.price - (fee if ex.fee_asset == ex.quote else ZERO)
        sell_fee_brl = _value_brl(ex.fee_asset, fee, ex, brl) if fee else ZERO
        proceeds_brl = None if sell_fx is None else proceeds_quote * sell_fx
        if proceeds_brl is not None and fee and ex.fee_asset not in (ex.base, ex.quote):
            proceeds_brl = None if sell_fee_brl is None else proceeds_brl - sell_fee_brl

        remaining = sold
        queue = lots[ex.base]
        while remaining > EPS:
            lot = queue[0] if queue else None
            if lot is not None:
                take = min(lot.remaining, remaining)
                lot.remaining -= take
                if lot.remaining <= EPS:
                    queue.popleft()
            else:
                take = remaining
            remaining -= take
            share = take / sold  # fração desta venda
            out.append(_closed_row(ex, lot, take, share, proceeds_quote, proceeds_brl, sell_fx, fee, sell_fee_brl))

    for asset, queue in lots.items():
        for lot in queue:
            if lot.remaining > EPS:
                out.append(_open_row(asset, lot))
    return out


def _buy_part(c: Cycle, lot: _Lot, take_net: Decimal) -> Decimal | None:
    """Preenche as colunas de compra para ``take_net`` unidades do lote. Retorna o custo em BRL."""
    frac = take_net / lot.net if lot.net else ZERO
    ex = lot.ex
    c.buy_execution_id, c.buy_connection_id, c.buy_at, c.buy_quote = ex.id, ex.connection_id, ex.at, ex.quote
    c.buy_quantity = lot.gross * frac
    c.buy_price = ex.price
    c.buy_fee = lot.fee_qty * frac if lot.fee_qty else ZERO
    c.buy_fee_asset = lot.fee_asset
    c.buy_total = lot.gross * frac * ex.price
    c.buy_fx = lot.fx
    c.buy_total_brl = None if lot.cost_brl is None else lot.cost_brl * frac
    return c.buy_total_brl


def _closed_row(ex: Exec, lot: _Lot | None, take: Decimal, share: Decimal, proceeds_quote, proceeds_brl, sell_fx, fee, sell_fee_brl) -> Cycle:
    c = Cycle(status="closed", asset=ex.base)
    c.source = lot.ex.source if lot else ex.source
    c.sell_execution_id, c.sell_connection_id, c.sell_at, c.sell_quote = ex.id, ex.connection_id, ex.at, ex.quote
    c.sell_quantity = take
    c.sell_price = ex.price
    c.sell_fee = fee * share if fee else ZERO
    c.sell_fee_asset = ex.fee_asset
    # Calcula pela quantidade do pedaço (evita arredondamento de frações como 1/3).
    sold_part = take if ex.fee_asset != ex.base else ex.quantity * share
    c.sell_total = sold_part * ex.price - (c.sell_fee if ex.fee_asset == ex.quote else ZERO)
    c.sell_fx = sell_fx
    if proceeds_brl is None or sell_fx is None:
        c.sell_total_brl = None
    else:
        other_fee = (sell_fee_brl or ZERO) * share if fee and ex.fee_asset not in (ex.base, ex.quote) else ZERO
        c.sell_total_brl = c.sell_total * sell_fx - other_fee

    notes = []
    if lot is None:
        c.complete = False
        notes.append("Sem compra registrada para esta quantidade (depósito externo ou histórico anterior não importado).")
    else:
        cost_brl = _buy_part(c, lot, take)
        if cost_brl is None or c.sell_total_brl is None:
            c.complete = False
            notes.append("Câmbio ou cotação indisponível para converter em BRL.")
        else:
            c.pnl_brl = c.sell_total_brl - cost_brl
            c.pnl_pct = c.pnl_brl / cost_brl * 100 if cost_brl else None
            if lot.fx is not None and sell_fx is not None:
                c.fx_effect_brl = c.buy_total * (sell_fx - lot.fx) if lot.ex.quote == ex.quote else None
        if lot.ex.quote == ex.quote:
            frac = take / lot.net if lot.net else ZERO
            c.pnl_quote = c.sell_total - lot.cost_quote * frac
        c.holding_days = Decimal((ex.at - lot.ex.at).total_seconds()) / Decimal(86400)
        frac = take / lot.net if lot.net else ZERO
        buy_fee_brl = None if lot.fee_brl is None else lot.fee_brl * frac
        sfee = None if sell_fee_brl is None else sell_fee_brl * share
        c.fees_brl = None if buy_fee_brl is None or sfee is None else buy_fee_brl + sfee
    c.note = " ".join(notes) or None
    return c


def _open_row(asset: str, lot: _Lot) -> Cycle:
    c = Cycle(status="open", asset=asset, source=lot.ex.source)
    _buy_part(c, lot, lot.remaining)
    c.sell_quantity = lot.remaining
    frac = lot.remaining / lot.net if lot.net else ZERO
    c.fees_brl = None if lot.fee_brl is None else lot.fee_brl * frac
    if c.buy_total_brl is None:
        c.complete = False
        c.note = "Câmbio indisponível para converter a compra em BRL."
    return c
