from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.modules.trades.pnl.engine import LedgerMovement, LedgerTrade, compute

T = datetime(2026, 1, 1, tzinfo=UTC)
PRICES = {"BNB": D("500"), "BTC": D("60000"), "ETH": D("3000")}


def price(asset, at):
    return PRICES.get(asset)


def tr(i, side, qty, quote_qty, base="BTC", quote="USDT", fee="0", fee_asset=None):
    return LedgerTrade(uuid.uuid4(), None, T + timedelta(minutes=i), base, quote, side, D(qty), D(quote_qty), D(fee), fee_asset)


def run(trades, movements=(), method="FIFO"):
    return compute(list(trades), list(movements), base_currency="USDT", method=method, price=price)


def sales(res):
    return [r for r in res.realized if r.kind == "sale"]


def test_fifo_consumes_oldest_lots():
    res = run([tr(1, "BUY", "1", "10000"), tr(2, "BUY", "1", "20000"), tr(3, "SELL", "1.5", "45000")])
    s = sales(res)[0]
    assert s.cost_basis == D("20000")  # 1×10000 + 0.5×20000
    assert s.realized_pnl == D("25000")
    assert res.positions["BTC"].quantity == D("0.5")
    assert res.positions["BTC"].cost_basis == D("10000")


def test_average_cost_method():
    res = run([tr(1, "BUY", "1", "10000"), tr(2, "BUY", "1", "20000"), tr(3, "SELL", "1.5", "45000")], method="AVERAGE")
    s = sales(res)[0]
    assert s.cost_basis == D("22500")
    assert s.realized_pnl == D("22500")
    assert res.positions["BTC"].cost_basis == D("7500")


def test_fee_in_quote_affects_cost_and_proceeds():
    res = run([tr(1, "BUY", "1", "10000", fee="10", fee_asset="USDT"), tr(2, "SELL", "1", "12000", fee="12", fee_asset="USDT")])
    s = sales(res)[0]
    assert s.cost_basis == D("10010") and s.proceeds == D("11988")
    assert s.realized_pnl == D("1978")
    assert res.fees_total == D("22")


def test_fee_in_base_reduces_received_quantity():
    res = run([tr(1, "BUY", "1", "10000", fee="0.001", fee_asset="BTC")])
    assert res.positions["BTC"].quantity == D("0.999")
    assert res.positions["BTC"].cost_basis == D("10000")
    assert res.fees_total == D("10")


def test_fee_in_bnb_consumes_bnb_lots():
    res = run([
        tr(1, "BUY", "1", "300", base="BNB"),
        tr(2, "BUY", "1", "10000", fee="0.02", fee_asset="BNB"),
    ])
    assert res.positions["BNB"].quantity == D("0.98")
    fee_rec = [r for r in res.realized if r.kind == "fee"][0]
    assert fee_rec.asset == "BNB" and fee_rec.proceeds == D("10") and fee_rec.cost_basis == D("6")
    assert res.positions["BTC"].cost_basis == D("10010")  # 10000 + 0.02×500


def test_deposit_is_not_profit_and_unknown_cost_is_incomplete():
    dep = LedgerMovement(None, None, T, "deposit", "BTC", D("1"))
    res = run([tr(5, "SELL", "1", "60000")], [dep])
    s = sales(res)[0]
    assert s.status == "incomplete" and s.realized_pnl is None and s.cost_basis is None
    assert "Custo desconhecido" in s.note
    assert res.external_deposits_unknown_cost == {"BTC": D("1")}


def test_cash_deposit_and_withdrawal_do_not_generate_pnl():
    res = run([], [LedgerMovement(None, None, T, "deposit", "USDT", D("1000")), LedgerMovement(None, None, T + timedelta(hours=1), "withdrawal", "USDT", D("400"), D("1"))])
    assert res.realized == []
    assert res.positions["USDT"].quantity == D("599")
    assert res.deposits_base == D("1000") and res.withdrawals_base == D("400")
    assert res.fees_total == D("1")


def test_internal_transfer_preserves_cost_basis():
    a, b = uuid.uuid4(), uuid.uuid4()
    buy = LedgerTrade(uuid.uuid4(), a, T, "BTC", "USDT", "BUY", D("1"), D("10000"), D(0), None)
    w = LedgerMovement(None, a, T + timedelta(hours=1), "withdrawal", "BTC", D("1"), D(0), "tx-1", internal=True)
    d = LedgerMovement(None, b, T + timedelta(hours=2), "deposit", "BTC", D("1"), D(0), "tx-1", internal=True)
    sell = LedgerTrade(uuid.uuid4(), b, T + timedelta(hours=3), "BTC", "USDT", "SELL", D("1"), D("15000"), D(0), None)
    res = compute([buy, sell], [w, d], base_currency="USDT", method="FIFO", price=price)
    s = sales(res)[0]
    assert s.status == "complete" and s.cost_basis == D("10000") and s.realized_pnl == D("5000")
    assert res.internal_transfers == 1


def test_sell_without_history_is_incomplete():
    res = run([tr(1, "SELL", "1", "60000")])
    assert sales(res)[0].status == "incomplete"


def test_crypto_to_crypto_conversion_realizes_quote_asset():
    # compra 1 ETH a 2000 USDT; depois compra BTC pagando 1 ETH (ETH vale 3000 no momento)
    res = run([tr(1, "BUY", "1", "2000", base="ETH"), tr(2, "BUY", "0.05", "1", base="BTC", quote="ETH")])
    conv = [r for r in res.realized if r.kind == "conversion"][0]
    assert conv.asset == "ETH" and conv.proceeds == D("3000") and conv.realized_pnl == D("1000")
    assert res.positions["BTC"].cost_basis == D("3000")
    assert "ETH" not in res.positions


def test_missing_price_marks_incomplete():
    res = compute([tr(1, "BUY", "1", "10", base="XYZ", quote="ABC")], [], base_currency="USDT", method="FIFO", price=lambda a, t: None)
    assert res.positions["XYZ"].cost_basis is None
    assert all(r.status == "incomplete" for r in res.realized)
