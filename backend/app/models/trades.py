"""Entidades do módulo Trades e de integrações com corretoras."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import Amount, TimestampMixin, utcnow, uuid_pk


class ConnectionStatus:
    PENDING = "pending_validation"
    ACTIVE = "active"
    SYNCING = "syncing"
    ERROR = "error"
    INVALID_CREDENTIALS = "invalid_credentials"
    SUSPENDED = "suspended"
    ALL = (PENDING, ACTIVE, SYNCING, ERROR, INVALID_CREDENTIALS, SUSPENDED)


class ExchangeProvider(Base):
    __tablename__ = "exchange_providers"
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class ExchangeConnection(TimestampMixin, Base):
    __tablename__ = "exchange_connections"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exchange_providers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ConnectionStatus.PENDING)
    status_message: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    provider: Mapped[ExchangeProvider] = relationship(lazy="joined")
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_exchange_connections_user_name"),
        Index("ix_exchange_connections_user", "user_id"),
    )


class SyncJob(Base):
    """Fila de sincronização no PostgreSQL (consumida com FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "sync_jobs"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="incremental")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="schedule")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        Index("ix_sync_jobs_status_run_after", "status", "run_after"),
        Index("ix_sync_jobs_connection_created", "connection_id", "created_at"),
    )


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoints"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    stream: Mapped[str] = mapped_column(String(80), nullable=False)
    cursor: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint("connection_id", "stream", name="uq_sync_checkpoints_stream"),)


class ExchangeOrder(TimestampMixin, Base):
    __tablename__ = "exchange_orders"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False, default="spot")
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    base_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    order_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Amount)
    orig_qty: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    executed_qty: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    cumulative_quote_qty: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exchange_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_exchange_orders_external"),
        Index("ix_exchange_orders_user_placed", "user_id", "placed_at"),
    )


class TradeExecution(Base):
    """Execução (fill). Uma ordem pode ter várias execuções.

    Idempotência: ``(connection_id, idempotency_key)`` é único. A chave é
    ``ext:<id externo>`` quando a corretora fornece um identificador confiável, ou
    ``hash:<sha256 dos campos>`` para importações sem identificador (ver docs).
    """

    __tablename__ = "trade_executions"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exchange_orders.id", ondelete="SET NULL"))
    external_order_id: Mapped[str | None] = mapped_column(String(80))
    external_id: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False, default="spot")
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    base_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    price: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    quote_quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    fee: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=0)
    fee_asset: Mapped[str | None] = mapped_column(String(20))
    # Valor da taxa na moeda-base do usuário (preenchido pela apuração; None = sem cotação).
    fee_value: Mapped[Decimal | None] = mapped_column(Amount)
    fee_value_currency: Mapped[str | None] = mapped_column(String(16))
    is_maker: Mapped[bool | None] = mapped_column(Boolean)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="api")
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="synced")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    connection: Mapped[ExchangeConnection] = relationship(lazy="joined")
    __table_args__ = (
        UniqueConstraint("connection_id", "idempotency_key", name="uq_trade_executions_idempotency"),
        Index("ix_trade_executions_user_executed", "user_id", "executed_at"),
        Index("ix_trade_executions_symbol", "symbol"),
    )


class AssetMovement(Base):
    """Depósitos e retiradas (necessários para conciliação e para não confundir aporte com lucro)."""

    __tablename__ = "asset_movements"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # deposit | withdrawal
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    asset: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    fee: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=0)
    network: Mapped[str | None] = mapped_column(String(40))
    tx_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        UniqueConstraint("connection_id", "kind", "external_id", name="uq_asset_movements_external"),
        Index("ix_asset_movements_user_occurred", "user_id", "occurred_at"),
    )


class Balance(Base):
    """Saldo informado pela corretora (última leitura)."""

    __tablename__ = "balances"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    asset: Mapped[str] = mapped_column(String(20), nullable=False)
    free: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    locked: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    total: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("connection_id", "asset", name="uq_balances_connection_asset"),)


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    asset: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Amount)
    value: Mapped[Decimal | None] = mapped_column(Amount)
    price_source: Mapped[str | None] = mapped_column(String(60))
    price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_balance_snapshots_user_taken", "user_id", "taken_at"),)


class AssetPrice(Base):
    """Cotações usadas em valorizações, sempre com fonte e horário."""

    __tablename__ = "asset_prices"
    id: Mapped[uuid.UUID] = uuid_pk()
    base_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    price_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        UniqueConstraint("base_asset", "quote_asset", "source", "price_at", name="uq_asset_prices_point"),
        Index("ix_asset_prices_lookup", "base_asset", "quote_asset", "price_at"),
    )


class Position(Base):
    """Posição calculada localmente a partir do histórico (método FIFO ou custo médio)."""

    __tablename__ = "positions"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset: Mapped[str] = mapped_column(String(20), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    cost_basis: Mapped[Decimal | None] = mapped_column(Amount)
    cost_basis_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unknown_cost_quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "asset", name="uq_positions_user_asset"),)


class RealizedPnlRecord(Base):
    __tablename__ = "realized_pnl_records"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE")
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade_executions.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # sale | conversion | fee
    asset: Mapped[str] = mapped_column(String(20), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    proceeds: Mapped[Decimal | None] = mapped_column(Amount)
    cost_basis: Mapped[Decimal | None] = mapped_column(Amount)
    fees: Mapped[Decimal | None] = mapped_column(Amount)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Amount)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # complete | incomplete
    note: Mapped[str | None] = mapped_column(Text)
    realized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_realized_pnl_user_realized", "user_id", "realized_at"),)


class CycleStatus:
    BUY_ORDER = "buy_order"  # Ordem Comprar
    OPEN = "open"  # Ativo
    SELL_ORDER = "sell_order"  # Ordem Vender
    CLOSED = "closed"  # Concluído


class TradeCycle(Base):
    """Operação compra → venda: um lote comprado e a venda que o encerrou (FIFO por ativo).

    Recalculada a partir das execuções a cada apuração. Valores em BRL usam a cotação
    histórica do minuto de cada execução.
    """

    __tablename__ = "trade_cycles"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    asset: Mapped[str] = mapped_column(String(20), nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(20))  # api

    buy_execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trade_executions.id", ondelete="CASCADE"))
    buy_connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exchange_connections.id", ondelete="CASCADE"))
    buy_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    buy_quote: Mapped[str | None] = mapped_column(String(20))
    buy_quantity: Mapped[Decimal | None] = mapped_column(Amount)
    buy_price: Mapped[Decimal | None] = mapped_column(Amount)
    buy_fee: Mapped[Decimal | None] = mapped_column(Amount)
    buy_fee_asset: Mapped[str | None] = mapped_column(String(20))
    buy_total: Mapped[Decimal | None] = mapped_column(Amount)
    buy_fx: Mapped[Decimal | None] = mapped_column(Amount)
    buy_total_brl: Mapped[Decimal | None] = mapped_column(Amount)

    sell_execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trade_executions.id", ondelete="CASCADE"))
    sell_connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exchange_connections.id", ondelete="CASCADE"))
    sell_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exchange_orders.id", ondelete="CASCADE"))
    sell_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sell_quote: Mapped[str | None] = mapped_column(String(20))
    sell_quantity: Mapped[Decimal | None] = mapped_column(Amount)
    sell_price: Mapped[Decimal | None] = mapped_column(Amount)
    sell_fee: Mapped[Decimal | None] = mapped_column(Amount)
    sell_fee_asset: Mapped[str | None] = mapped_column(String(20))
    sell_total: Mapped[Decimal | None] = mapped_column(Amount)
    sell_fx: Mapped[Decimal | None] = mapped_column(Amount)
    sell_total_brl: Mapped[Decimal | None] = mapped_column(Amount)

    pnl_brl: Mapped[Decimal | None] = mapped_column(Amount)
    pnl_pct: Mapped[Decimal | None] = mapped_column(Amount)
    pnl_quote: Mapped[Decimal | None] = mapped_column(Amount)
    fx_effect_brl: Mapped[Decimal | None] = mapped_column(Amount)
    fees_brl: Mapped[Decimal | None] = mapped_column(Amount)
    holding_days: Mapped[Decimal | None] = mapped_column(Amount)
    ref_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # venda se concluído; senão compra
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        Index("ix_trade_cycles_user_ref", "user_id", "ref_at"),
        Index("ix_trade_cycles_user_asset", "user_id", "asset"),
    )
