"""Motor de apuração de resultados (puro, sem banco).

Metodologia (documentada em docs/ARCHITECTURE.md):

- Todos os valores são apurados na moeda-base do usuário (R), com cotação
  fornecida por ``price(asset, at)``. A moeda-base é tratada como caixa.
- Compra BASE/QUOTE: entrega QUOTE (realiza ganho/perda do QUOTE se ele não for R)
  e adquire BASE com custo = valor entregue + taxa.
- Venda BASE/QUOTE: entrega BASE (gera registro de resultado realizado) e adquire
  QUOTE com custo igual ao valor recebido.
- Taxa paga em um terceiro ativo (ex.: BNB) consome lotes desse ativo.
- Depósito externo de ativo ≠ R entra com custo DESCONHECIDO. Vendas desses
  lotes geram resultado "incompleto" — nunca inventamos custo.
- Depósito/retirada não geram lucro/prejuízo. Transferências entre contas do
  próprio usuário (mesmo tx_id) preservam o custo original.
- Falta de cotação ou de histórico → registro "incompleto".
- Métodos: FIFO (lotes por ordem de aquisição) ou AVERAGE (custo médio
  ponderado; consumo proporcional entre parte de custo conhecido e desconhecido).
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

ZERO = Decimal(0)
EPS = Decimal("1e-10")

PriceFn = Callable[[str, datetime], Decimal | None]


@dataclass(frozen=True)
class LedgerTrade:
    id: uuid.UUID | None
    connection_id: uuid.UUID | None
    at: datetime
    base: str
    quote: str
    side: str
    quantity: Decimal
    quote_quantity: Decimal
    fee: Decimal
    fee_asset: str | None


@dataclass(frozen=True)
class LedgerMovement:
    id: uuid.UUID | None
    connection_id: uuid.UUID | None
    at: datetime
    kind: str  # deposit | withdrawal
    asset: str
    amount: Decimal
    fee: Decimal = ZERO
    tx_id: str | None = None
    internal: bool = False


@dataclass
class Lot:
    qty: Decimal
    cost: Decimal | None  # custo total do lote na moeda-base; None = desconhecido


@dataclass
class RealizedOut:
    kind: str  # sale | conversion | fee
    asset: str
    quantity: Decimal
    proceeds: Decimal | None
    cost_basis: Decimal | None
    fees: Decimal | None
    realized_pnl: Decimal | None
    status: str
    note: str | None
    at: datetime
    connection_id: uuid.UUID | None
    execution_id: uuid.UUID | None


@dataclass
class PositionOut:
    asset: str
    quantity: Decimal
    known_cost: Decimal
    unknown_qty: Decimal

    @property
    def complete(self) -> bool:
        return self.unknown_qty <= EPS

    @property
    def cost_basis(self) -> Decimal | None:
        return self.known_cost if self.complete else None


@dataclass
class EngineResult:
    realized: list[RealizedOut] = field(default_factory=list)
    positions: dict[str, PositionOut] = field(default_factory=dict)
    fees_total: Decimal = ZERO
    fees_incomplete: int = 0
    deposits_base: Decimal = ZERO
    withdrawals_base: Decimal = ZERO
    external_deposits_unknown_cost: dict[str, Decimal] = field(default_factory=dict)
    internal_transfers: int = 0
    trade_fee_values: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Book:
    def __init__(self, base_currency: str, method: str = "FIFO"):
        if method not in ("FIFO", "AVERAGE"):
            raise ValueError(method)
        self.r = base_currency
        self.method = method
        self.lots: dict[str, deque[Lot]] = defaultdict(deque)
        self.cash = ZERO

    def acquire_lots(self, asset: str, lots: list[Lot]) -> None:
        for lot in lots:
            self.acquire(asset, lot.qty, lot.cost)

    def acquire(self, asset: str, qty: Decimal, cost: Decimal | None) -> None:
        if qty <= 0:
            return
        if asset == self.r:
            self.cash += qty
            return
        q = self.lots[asset]
        if self.method == "AVERAGE":
            # Até dois lotes: [0] custo conhecido (médio), [1] custo desconhecido.
            if not q:
                q.extend([Lot(ZERO, ZERO), Lot(ZERO, None)])
            if cost is None:
                q[1].qty += qty
            else:
                q[0].qty += qty
                q[0].cost = (q[0].cost or ZERO) + cost
        else:
            q.append(Lot(qty, cost))

    def take(self, asset: str, qty: Decimal) -> tuple[list[Lot], Decimal]:
        """Remove ``qty`` do ativo. Retorna os pedaços de lotes removidos e a quantidade sem lote (falta de histórico)."""
        if qty <= 0:
            return [], ZERO
        if asset == self.r:
            self.cash -= qty
            return [Lot(qty, qty)], ZERO
        q = self.lots[asset]
        taken: list[Lot] = []
        if self.method == "AVERAGE":
            total = sum((lot.qty for lot in q), ZERO)
            if total <= 0:
                return [], qty
            portion = min(qty, total)
            for lot in q:
                if lot.qty <= 0:
                    continue
                part = portion * lot.qty / total
                cost = None if lot.cost is None else lot.cost * part / lot.qty
                taken.append(Lot(part, cost))
                lot.qty -= part
                if lot.cost is not None:
                    lot.cost -= cost or ZERO
            shortfall = qty - portion
            return taken, shortfall if shortfall > EPS else ZERO

        remaining = qty
        while remaining > EPS and q:
            lot = q[0]
            if lot.qty <= remaining + EPS:
                taken.append(Lot(lot.qty, lot.cost))
                remaining -= lot.qty
                q.popleft()
            else:
                cost = None if lot.cost is None else lot.cost * remaining / lot.qty
                taken.append(Lot(remaining, cost))
                lot.cost = None if lot.cost is None else lot.cost - (cost or ZERO)
                lot.qty -= remaining
                remaining = ZERO
        return taken, remaining if remaining > EPS else ZERO

    def dispose(self, asset: str, qty: Decimal) -> tuple[Decimal, Decimal]:
        """Retorna (custo conhecido consumido, quantidade com custo desconhecido)."""
        taken, shortfall = self.take(asset, qty)
        known = sum((lot.cost for lot in taken if lot.cost is not None), ZERO)
        unknown = sum((lot.qty for lot in taken if lot.cost is None), ZERO) + shortfall
        return known, unknown

    def positions(self) -> dict[str, PositionOut]:
        out: dict[str, PositionOut] = {}
        for asset, lots in self.lots.items():
            qty = sum((lot.qty for lot in lots), ZERO)
            if qty <= EPS:
                continue
            known = sum((lot.cost for lot in lots if lot.cost is not None), ZERO)
            unknown = sum((lot.qty for lot in lots if lot.cost is None), ZERO)
            out[asset] = PositionOut(asset, qty, known, unknown)
        if self.cash > EPS or self.cash < -EPS:
            out[self.r] = PositionOut(self.r, self.cash, self.cash, ZERO)
        return out


def _realized(
    kind: str,
    asset: str,
    qty: Decimal,
    proceeds: Decimal | None,
    known_cost: Decimal,
    unknown_qty: Decimal,
    fees: Decimal | None,
    at: datetime,
    t: LedgerTrade,
) -> RealizedOut:
    notes = []
    if unknown_qty > EPS:
        notes.append(
            f"Custo desconhecido para {unknown_qty.normalize():f} {asset} (histórico incompleto ou depósito externo)."
        )
    if proceeds is None:
        notes.append("Cotação indisponível no horário da operação.")
    complete = not notes
    return RealizedOut(
        kind=kind,
        asset=asset,
        quantity=qty,
        proceeds=proceeds,
        cost_basis=known_cost if unknown_qty <= EPS else None,
        fees=fees,
        realized_pnl=(proceeds - known_cost) if complete and proceeds is not None else None,
        status="complete" if complete else "incomplete",
        note=" ".join(notes) or None,
        at=at,
        connection_id=t.connection_id,
        execution_id=t.id,
    )


def compute(
    trades: list[LedgerTrade],
    movements: list[LedgerMovement],
    *,
    base_currency: str,
    method: str,
    price: PriceFn,
) -> EngineResult:
    r = base_currency
    book = Book(r, method)
    res = EngineResult()
    in_transit: dict[str, list[Lot]] = {}

    def value(asset: str, amount: Decimal, at: datetime) -> Decimal | None:
        if amount == 0:
            return ZERO
        if asset == r:
            return amount
        p = price(asset, at)
        return None if p is None else amount * p

    # Ordem no mesmo instante: depósitos, compras, vendas, retiradas.
    events: list[tuple[datetime, int, object]] = []
    for m in movements:
        events.append((m.at, 0 if m.kind == "deposit" else 3, m))
    for t in trades:
        events.append((t.at, 1 if t.side == "BUY" else 2, t))
    events.sort(key=lambda e: (e[0], e[1]))

    for at, _, ev in events:
        if isinstance(ev, LedgerMovement):
            _apply_movement(ev, book, res, in_transit, value, r)
            continue
        t: LedgerTrade = ev  # type: ignore[assignment]
        q, Q, f, F = t.quantity, t.quote_quantity, t.fee or ZERO, t.fee_asset
        if q <= 0:
            continue
        gross = value(t.quote, Q, at)
        fee_value: Decimal | None
        if f == 0 or F is None:
            fee_value, f = ZERO, ZERO
        elif F == t.base:
            fee_value = None if gross is None else gross / q * f
        elif F == t.quote:
            fee_value = None if gross is None or Q == 0 else gross / Q * f
        else:
            fee_value = value(F, f, at)
        if fee_value is None:
            res.fees_incomplete += 1
        else:
            res.fees_total += fee_value
        if t.id is not None:
            res.trade_fee_values[t.id] = fee_value

        if t.side == "BUY":
            known_q, unk_q = book.dispose(t.quote, Q)
            if t.quote != r:
                res.realized.append(_realized("conversion", t.quote, Q, gross, known_q, unk_q, None, at, t))
            net_base = q
            if F == t.base:
                net_base = q - f
                cost = gross
            elif F == t.quote:
                known_f, unk_f = book.dispose(t.quote, f)
                if t.quote != r:
                    res.realized.append(_realized("fee", t.quote, f, fee_value, known_f, unk_f, None, at, t))
                cost = None if gross is None or fee_value is None else gross + fee_value
            elif f > 0:
                known_f, unk_f = book.dispose(F, f)  # type: ignore[arg-type]
                if F != r:
                    res.realized.append(_realized("fee", F, f, fee_value, known_f, unk_f, None, at, t))  # type: ignore[arg-type]
                cost = None if gross is None or fee_value is None else gross + fee_value
            else:
                cost = gross
            book.acquire(t.base, net_base, cost)
        else:  # SELL
            if F == t.base:
                known_b, unk_b = book.dispose(t.base, q + f)
                proceeds = gross
                received_quote, quote_cost = Q, gross
                sold_qty = q + f
            else:
                known_b, unk_b = book.dispose(t.base, q)
                sold_qty = q
                if F == t.quote and f > 0:
                    received_quote = Q - f
                    proceeds = None if gross is None or fee_value is None else gross - fee_value
                    quote_cost = proceeds
                elif f > 0:
                    known_f, unk_f = book.dispose(F, f)  # type: ignore[arg-type]
                    if F != r:
                        res.realized.append(_realized("fee", F, f, fee_value, known_f, unk_f, None, at, t))  # type: ignore[arg-type]
                    received_quote, quote_cost = Q, gross
                    proceeds = None if gross is None or fee_value is None else gross - fee_value
                else:
                    received_quote, quote_cost, proceeds = Q, gross, gross
            res.realized.append(_realized("sale", t.base, sold_qty, proceeds, known_b, unk_b, fee_value, at, t))
            book.acquire(t.quote, received_quote, quote_cost)

    for tx in in_transit:
        res.warnings.append(f"Transferência {tx[:12]}… saiu de uma conta e ainda não foi identificada na outra.")
    res.positions = book.positions()
    return res


def _apply_movement(m: LedgerMovement, book: Book, res: EngineResult, in_transit, value, r: str) -> None:
    if m.kind == "deposit":
        if m.internal and m.tx_id and m.tx_id in in_transit:
            book.acquire_lots(m.asset, in_transit.pop(m.tx_id))
            res.internal_transfers += 1
            return
        if m.asset == r:
            book.acquire(r, m.amount, m.amount)
            res.deposits_base += m.amount
            return
        book.acquire(m.asset, m.amount, None)
        res.external_deposits_unknown_cost[m.asset] = (
            res.external_deposits_unknown_cost.get(m.asset, ZERO) + m.amount
        )
        v = value(m.asset, m.amount, m.at)
        if v is not None:
            res.deposits_base += v
        return

    # retirada
    if m.fee > 0:
        book.dispose(m.asset, m.fee)
        fv = value(m.asset, m.fee, m.at)
        if fv is None:
            res.fees_incomplete += 1
        else:
            res.fees_total += fv
    if m.internal and m.tx_id:
        lots, shortfall = book.take(m.asset, m.amount)
        if shortfall > 0:
            lots.append(Lot(shortfall, None))
        in_transit[m.tx_id] = lots
        return
    book.take(m.asset, m.amount)
    v = value(m.asset, m.amount, m.at)
    if v is not None:
        res.withdrawals_base += v
