"""Corretora e fonte de preços simuladas para os testes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.integrations.base import (
    BalanceDTO,
    Capabilities,
    CredentialField,
    ExchangeAdapter,
    ExecutionDTO,
    InvalidCredentials,
    MovementDTO,
    OrderDTO,
    Page,
    PriceSource,
    ProviderInfo,
    SymbolInfo,
    TemporaryError,
    ValidationResult,
)

BTCUSDT = SymbolInfo("BTCUSDT", "BTC", "USDT")
T0 = datetime(2026, 1, 1, tzinfo=UTC)
GOOD_KEY = "A" * 64
GOOD_SECRET = "S3cr3t" + "x" * 58


def ex(i: int, side: str, qty: str, price: str, fee: str = "0", fee_asset: str | None = "USDT", minutes: int | None = None) -> ExecutionDTO:
    q, p = Decimal(qty), Decimal(price)
    return ExecutionDTO(
        external_id=str(i),
        external_order_id=str(1000 + i),
        symbol=BTCUSDT,
        side=side,
        quantity=q,
        price=p,
        quote_quantity=q * p,
        fee=Decimal(fee),
        fee_asset=fee_asset,
        is_maker=False,
        executed_at=T0 + timedelta(minutes=minutes if minutes is not None else i),
    )


class FakeExchange:
    """Estado compartilhado entre instâncias do adaptador simulado."""

    def __init__(self):
        self.balances = [BalanceDTO("BTC", Decimal("0.5"), Decimal(0)), BalanceDTO("USDT", Decimal("1000"), Decimal(0))]
        self.executions: list[ExecutionDTO] = []
        self.orders: list[OrderDTO] = []
        self.movements: list[MovementDTO] = []
        self.page_size = 2
        self.fail_on_call: int | None = None  # número da chamada fetch_executions que falha
        self.fail_with: Exception = TemporaryError("Falha simulada")
        self.calls = 0
        self.invalid = False


class FakeAdapter(ExchangeAdapter):
    info = ProviderInfo(
        key="binance",
        name="Binance (simulada)",
        credential_fields=(CredentialField("api_key", "API Key", False), CredentialField("api_secret", "Secret Key", True)),
        instructions=("Simulação",),
        capabilities=Capabilities(deposits=True, withdrawals=False),
    )
    state = FakeExchange()

    def __init__(self, credentials, settings=None):
        super().__init__(credentials, settings)
        if credentials.get("api_secret") != GOOD_SECRET or self.state.invalid:
            self._invalid = True
        else:
            self._invalid = False

    def _check(self):
        if self._invalid:
            raise InvalidCredentials("Credencial rejeitada pela corretora simulada.")

    def validate_credentials(self):
        self._check()
        return ValidationResult(True, "active", "ok", warnings=["Restrinja por IP"])

    def fetch_balances(self):
        self._check()
        return list(self.state.balances)

    def discover_symbols(self, assets, extra_symbols):
        return [BTCUSDT]

    def fetch_executions(self, symbol, cursor):
        self._check()
        self.state.calls += 1
        if self.state.fail_on_call is not None and self.state.calls == self.state.fail_on_call:
            raise self.state.fail_with
        start = int(cursor.get("from", 0))
        items = self.state.executions[start : start + self.state.page_size]
        nxt = start + len(items)
        return Page(items, {"from": nxt}, has_more=nxt < len(self.state.executions))

    def fetch_orders(self, symbol, cursor):
        return Page(list(self.state.orders), {}, has_more=False)

    def fetch_movements(self, kind, cursor):
        items = [m for m in self.state.movements if m.kind == kind]
        return Page(items, {"done": True}, has_more=False)


class FakePrices(PriceSource):
    name = "fake"

    def __init__(self, prices: dict[tuple[str, str], Decimal] | None = None):
        self.prices = prices or {
            ("BTC", "USDT"): Decimal("60000"),
            ("BNB", "USDT"): Decimal("500"),
            ("ETH", "USDT"): Decimal("3000"),
            ("USDT", "BRL"): Decimal("5"),
        }

    def current_prices(self, wanted=None):
        return dict(self.prices)

    def historical_price(self, base, quote, at):
        return self.prices.get((base, quote))


def install(registry, state: FakeExchange | None = None, prices: FakePrices | None = None) -> FakeExchange:
    FakeAdapter.state = state or FakeExchange()
    registry.set_factories(lambda key, creds, settings: FakeAdapter(creds, settings), lambda: prices or FakePrices())
    return FakeAdapter.state
