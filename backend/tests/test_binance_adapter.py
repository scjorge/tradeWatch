"""Adaptador Binance contra respostas HTTP simuladas (respx). Nenhuma chave real é usada."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.integrations.base import InsufficientPermissions, InvalidCredentials, RateLimited, SymbolInfo, TemporaryError
from app.integrations.binance import adapter as binance
from app.integrations.binance.adapter import BinanceAdapter
from app.integrations.binance.client import BinanceClient

BASE = "https://api.binance.test"
KEY, SECRET = "k" * 64, "s" * 64
SYM = SymbolInfo("BTCUSDT", "BTC", "USDT")


@pytest.fixture
def mock():
    binance._exchange_info_cache.clear()
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        m.get("/api/v3/time").mock(return_value=httpx.Response(200, json={"serverTime": 1_700_000_000_000}))
        m.get("/api/v3/exchangeInfo").mock(
            return_value=httpx.Response(200, json={"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"}, {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC"}]})
        )
        yield m


def _adapter(settings=None):
    sleeps = []
    client = BinanceClient(KEY, SECRET, base_url=BASE, sleep=sleeps.append)
    return BinanceAdapter({"api_key": KEY, "api_secret": SECRET}, settings or {}, client=client), sleeps


RESTRICTIONS_OK = {"enableReading": True, "ipRestrict": False, "enableWithdrawals": False, "enableSpotAndMarginTrading": False}


def test_validate_read_only_key(mock):
    route = mock.get("/sapi/v1/account/apiRestrictions").mock(return_value=httpx.Response(200, json=RESTRICTIONS_OK))
    mock.get("/api/v3/account").mock(return_value=httpx.Response(200, json={"balances": []}))
    a, _ = _adapter()
    res = a.validate_credentials()
    assert res.ok and res.warnings  # recomenda restrição por IP
    req = route.calls[0].request
    assert req.headers["X-MBX-APIKEY"] == KEY
    assert "signature=" in str(req.url) and "timestamp=" in str(req.url)


def test_rejects_key_with_withdraw_or_trade(mock):
    mock.get("/sapi/v1/account/apiRestrictions").mock(
        return_value=httpx.Response(200, json={**RESTRICTIONS_OK, "enableWithdrawals": True, "enableSpotAndMarginTrading": True})
    )
    a, _ = _adapter()
    with pytest.raises(InsufficientPermissions) as e:
        a.validate_credentials()
    assert "saque" in str(e.value) and "negociação" in str(e.value)


def test_invalid_key_error_has_no_secret(mock):
    mock.get("/sapi/v1/account/apiRestrictions").mock(return_value=httpx.Response(401, json={"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}))
    a, _ = _adapter()
    with pytest.raises(InvalidCredentials) as e:
        a.validate_credentials()
    assert KEY not in str(e.value) and SECRET not in str(e.value)


def test_balances_and_trades_pagination(mock):
    mock.get("/api/v3/account").mock(return_value=httpx.Response(200, json={"balances": [{"asset": "BTC", "free": "0.1", "locked": "0.05"}, {"asset": "XRP", "free": "0", "locked": "0"}]}))
    trades = [
        {"symbol": "BTCUSDT", "id": 10, "orderId": 7, "price": "50000.1", "qty": "0.001", "quoteQty": "50.0001", "commission": "0.00000075", "commissionAsset": "BNB", "time": 1_700_000_000_000, "isBuyer": True, "isMaker": False},
        {"symbol": "BTCUSDT", "id": 11, "orderId": 8, "price": "51000", "qty": "0.001", "quoteQty": "51", "commission": "0.051", "commissionAsset": "USDT", "time": 1_700_000_100_000, "isBuyer": False, "isMaker": True},
    ]
    route = mock.get("/api/v3/myTrades").mock(return_value=httpx.Response(200, json=trades))
    a, _ = _adapter()
    bals = a.fetch_balances()
    assert [(b.asset, b.total) for b in bals] == [("BTC", Decimal("0.15"))]
    page = a.fetch_executions(SYM, {"from_id": 5})
    assert "fromId=5" in str(route.calls[0].request.url)
    assert page.next_cursor == {"from_id": 12} and page.has_more is False
    assert page.items[0].side == "BUY" and page.items[0].price == Decimal("50000.1")
    assert page.items[1].side == "SELL" and page.items[1].fee_asset == "USDT"


def test_orders_cursor_revisits_open_orders(mock):
    orders = [
        {"orderId": 1, "price": "1", "origQty": "1", "executedQty": "1", "cummulativeQuoteQty": "1", "status": "FILLED", "type": "LIMIT", "side": "BUY", "time": 1, "updateTime": 2},
        {"orderId": 2, "price": "1", "origQty": "1", "executedQty": "0", "cummulativeQuoteQty": "0", "status": "NEW", "type": "LIMIT", "side": "BUY", "time": 3, "updateTime": 3},
        {"orderId": 3, "price": "1", "origQty": "1", "executedQty": "1", "cummulativeQuoteQty": "1", "status": "FILLED", "type": "LIMIT", "side": "SELL", "time": 4, "updateTime": 5},
    ]
    mock.get("/api/v3/allOrders").mock(return_value=httpx.Response(200, json=orders))
    a, _ = _adapter()
    page = a.fetch_orders(SYM, {})
    assert page.next_cursor == {"order_id": 2}


def test_rate_limit_and_weight_throttle(mock):
    mock.get("/api/v3/myTrades").mock(return_value=httpx.Response(429, headers={"Retry-After": "30"}, json={"code": -1003, "msg": "Too many requests"}))
    a, _ = _adapter()
    with pytest.raises(RateLimited) as e:
        a.fetch_executions(SYM, {})
    assert e.value.retry_after == 30

    mock.get("/api/v3/account").mock(return_value=httpx.Response(200, headers={"x-mbx-used-weight-1m": "5900"}, json={"balances": []}))
    a2, sleeps = _adapter()
    a2.fetch_balances()
    assert sleeps and sleeps[-1] > 0


def test_server_errors_retry_then_temporary(mock):
    route = mock.get("/api/v3/account").mock(side_effect=[httpx.Response(502), httpx.Response(503), httpx.Response(200, json={"balances": []})])
    a, sleeps = _adapter()
    assert a.fetch_balances() == []
    assert route.call_count == 3 and sleeps == [2, 4]
    mock.get("/api/v3/account").mock(side_effect=httpx.ConnectTimeout("t"))
    a2, _ = _adapter()
    with pytest.raises(TemporaryError):
        a2.fetch_balances()


def test_discover_symbols_and_movements(mock):
    a, _ = _adapter({"history_start": "2026-01-01", "withdraw_pacing_seconds": 0})
    syms = a.discover_symbols({"BTC", "ETH"}, ["ethbtc"])
    assert [s.symbol for s in syms] == ["BTCUSDT", "ETHBTC"]
    mock.get("/sapi/v1/capital/deposit/hisrec").mock(
        return_value=httpx.Response(200, json=[{"id": "d1", "amount": "100", "coin": "USDT", "network": "TRX", "status": 1, "txId": "abc", "insertTime": 1_767_225_600_000}])
    )
    page = a.fetch_movements("deposit", {})
    assert page.items[0].status == "completed" and page.items[0].amount == Decimal("100")
    assert page.has_more is True  # ainda há janelas de 90 dias até hoje
