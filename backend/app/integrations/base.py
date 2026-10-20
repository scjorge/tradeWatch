"""Contrato comum para integrações com corretoras.

O módulo Trades depende apenas deste contrato. Cada corretora implementa um
adaptador próprio (ex.: ``app.integrations.binance``) que traduz a API externa
para os DTOs abaixo. Valores numéricos são sempre ``Decimal``; datas em UTC.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Generic, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------- erros
class AdapterError(Exception):
    """Erro definitivo da integração (não adianta repetir sem intervenção)."""


class InvalidCredentials(AdapterError):
    pass


class InsufficientPermissions(AdapterError):
    """A chave possui permissões além de leitura ou não possui leitura."""


class TemporaryError(Exception):
    """Falha transitória (rede, 5xx, timeout). Pode ser repetida com backoff."""


class RateLimited(TemporaryError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------- DTOs
@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    market: str = "spot"


@dataclass(frozen=True)
class BalanceDTO:
    asset: str
    free: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(frozen=True)
class OrderDTO:
    external_id: str
    symbol: SymbolInfo
    side: str  # BUY | SELL
    order_type: str
    status: str
    price: Decimal | None
    orig_qty: Decimal
    executed_qty: Decimal
    cumulative_quote_qty: Decimal
    placed_at: datetime
    updated_at: datetime | None
    is_final: bool


@dataclass(frozen=True)
class ExecutionDTO:
    external_id: str | None
    external_order_id: str | None
    symbol: SymbolInfo
    side: str
    quantity: Decimal
    price: Decimal
    quote_quantity: Decimal
    fee: Decimal
    fee_asset: str | None
    is_maker: bool | None
    executed_at: datetime


@dataclass(frozen=True)
class MovementDTO:
    kind: str  # deposit | withdrawal
    external_id: str
    asset: str
    amount: Decimal
    fee: Decimal
    network: str | None
    tx_id: str | None
    status: str  # completed | pending | failed
    occurred_at: datetime


@dataclass
class Page(Generic[T]):
    items: list[T]
    next_cursor: dict
    has_more: bool


@dataclass
class ValidationResult:
    ok: bool
    status: str  # active | invalid_credentials | error
    message: str
    warnings: list[str] = field(default_factory=list)
    permissions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool
    help: str = ""


@dataclass(frozen=True)
class Capabilities:
    balances: bool = True
    orders: bool = True
    executions: bool = True
    deposits: bool = False
    withdrawals: bool = False
    streams: bool = False
    read_only_enforced: bool = True
    rate_limit: str = ""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderInfo:
    key: str
    name: str
    credential_fields: tuple[CredentialField, ...]
    instructions: tuple[str, ...]
    capabilities: Capabilities
    docs_url: str = ""


# ---------------------------------------------------------------- contrato
class ExchangeAdapter(abc.ABC):
    info: ClassVar[ProviderInfo]

    def __init__(self, credentials: dict, settings: dict | None = None):
        self.credentials = credentials
        self.settings = settings or {}

    @abc.abstractmethod
    def validate_credentials(self) -> ValidationResult: ...

    @abc.abstractmethod
    def fetch_balances(self) -> list[BalanceDTO]: ...

    @abc.abstractmethod
    def discover_symbols(self, assets: set[str], extra_symbols: list[str]) -> list[SymbolInfo]:
        """Pares a sincronizar a partir dos ativos conhecidos e dos pares informados pelo usuário."""

    @abc.abstractmethod
    def fetch_executions(self, symbol: SymbolInfo, cursor: dict) -> Page[ExecutionDTO]: ...

    @abc.abstractmethod
    def fetch_orders(self, symbol: SymbolInfo, cursor: dict) -> Page[OrderDTO]: ...

    def fetch_movements(self, kind: str, cursor: dict) -> Page[MovementDTO]:
        return Page([], cursor, False)

    def close(self) -> None:  # pragma: no cover - opcional
        pass


class PriceSource(abc.ABC):
    """Fonte de cotações públicas (sem credenciais)."""

    name: str

    @abc.abstractmethod
    def current_prices(self, wanted: set[str] | None = None) -> dict[tuple[str, str], Decimal]:
        """Cotações atuais por par (base, cotação). ``wanted`` restringe aos pares formados por esses ativos."""

    @abc.abstractmethod
    def historical_price(self, base: str, quote: str, at: datetime) -> Decimal | None: ...
