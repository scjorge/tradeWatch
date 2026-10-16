"""Sincronização incremental, retomável e idempotente, independente da corretora.

Cada fluxo (saldos, depósitos, saques, ordens/execuções por par) avança por páginas;
após cada página o checkpoint é gravado na mesma transação dos dados. Se o
processo cair, a próxima execução retoma do último checkpoint. As restrições
de unicidade do banco garantem que reprocessar uma página não duplica registros.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.credentials import load_secret
from app.core.redaction import redact_text
from app.integrations.base import (
    AdapterError,
    ExchangeAdapter,
    ExecutionDTO,
    InsufficientPermissions,
    InvalidCredentials,
    PriceSource,
    RateLimited,
    TemporaryError,
)
from app.integrations.registry import build_adapter, build_price_source
from app.models import (
    AssetMovement,
    Balance,
    BalanceSnapshot,
    ConnectionStatus,
    ExchangeConnection,
    ExchangeOrder,
    SyncCheckpoint,
    SyncJob,
    TradeExecution,
    User,
)
from app.models.base import utcnow
from app.modules.notifications import service as notify
from app.modules.trades.pnl.service import recalculate_user
from app.modules.trades.pricing import CurrentPrices, refresh_current_prices

log = logging.getLogger("app.sync")

CONNECTION_OWNER = "exchange_connection"
MAX_PAGES_PER_STREAM = 500


# ------------------------------------------------------------------ fila
def enqueue_sync(
    db: Session, conn: ExchangeConnection, trigger: str, kind: str = "incremental", delay_seconds: int = 0
) -> SyncJob:
    existing = db.scalar(
        select(SyncJob).where(SyncJob.connection_id == conn.id, SyncJob.status.in_(("queued", "running")))
    )
    if existing:
        if trigger == "manual" and existing.status == "queued":
            existing.run_after = utcnow()
            existing.trigger = "manual"
        return existing
    job = SyncJob(
        user_id=conn.user_id,
        connection_id=conn.id,
        kind=kind,
        trigger=trigger,
        max_attempts=get_settings().job_max_attempts,
        run_after=utcnow() + timedelta(seconds=delay_seconds),
    )
    db.add(job)
    return job


def claim_next_job(db: Session, worker_id: str) -> SyncJob | None:
    job = db.scalar(
        select(SyncJob)
        .where(SyncJob.status == "queued", SyncJob.run_after <= utcnow())
        .order_by(SyncJob.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = "running"
    job.locked_by = worker_id
    job.started_at = utcnow()
    job.heartbeat_at = utcnow()
    job.attempts += 1
    db.commit()
    return job


def requeue_stale_jobs(db: Session) -> int:
    limit = utcnow() - timedelta(minutes=get_settings().job_stale_minutes)
    n = db.execute(
        update(SyncJob)
        .where(SyncJob.status == "running", SyncJob.heartbeat_at < limit)
        .values(status="queued", locked_by=None, run_after=utcnow(), error_message="Retomado após falha do worker.")
    ).rowcount
    db.commit()
    return n


# ------------------------------------------------------------------ helpers
def idempotency_key(dto: ExecutionDTO) -> str:
    if dto.external_id:
        return f"ext:{dto.external_id}"
    raw = "|".join(
        str(x)
        for x in (
            dto.symbol.symbol,
            dto.side,
            dto.executed_at.isoformat(),
            dto.quantity.normalize(),
            dto.price.normalize(),
            dto.fee.normalize(),
            dto.fee_asset or "",
            dto.external_order_id or "",
        )
    )
    return "hash:" + hashlib.sha256(raw.encode()).hexdigest()[:64]


def _checkpoint(db: Session, conn: ExchangeConnection, stream: str) -> SyncCheckpoint:
    cp = db.scalar(select(SyncCheckpoint).where(SyncCheckpoint.connection_id == conn.id, SyncCheckpoint.stream == stream))
    if cp is None:
        cp = SyncCheckpoint(user_id=conn.user_id, connection_id=conn.id, stream=stream, cursor={})
        db.add(cp)
        db.flush()
    return cp


def _heartbeat(db: Session, job: SyncJob) -> None:
    job.heartbeat_at = utcnow()


def insert_executions(db: Session, conn: ExchangeConnection, items: list[ExecutionDTO]) -> list[uuid.UUID]:
    if not items:
        return []
    rows = [
        {
            "id": uuid.uuid4(),
            "user_id": conn.user_id,
            "connection_id": conn.id,
            "external_id": e.external_id,
            "external_order_id": e.external_order_id,
            "idempotency_key": idempotency_key(e),
            "market": e.symbol.market,
            "symbol": e.symbol.symbol,
            "base_asset": e.symbol.base_asset,
            "quote_asset": e.symbol.quote_asset,
            "side": e.side,
            "quantity": e.quantity,
            "price": e.price,
            "quote_quantity": e.quote_quantity,
            "fee": e.fee,
            "fee_asset": e.fee_asset,
            "is_maker": e.is_maker,
            "executed_at": e.executed_at,
            "source": "api",
            "sync_status": "synced",
            "created_at": utcnow(),
        }
        for e in items
    ]
    stmt = (
        insert(TradeExecution)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_trade_executions_idempotency")
        .returning(TradeExecution.id)
    )
    return list(db.scalars(stmt))


def _sync_balances(db: Session, conn: ExchangeConnection, adapter: ExchangeAdapter) -> set[str]:
    balances = adapter.fetch_balances()
    now = utcnow()
    assets = set()
    for b in balances:
        assets.add(b.asset)
        db.execute(
            insert(Balance)
            .values(
                id=uuid.uuid4(), user_id=conn.user_id, connection_id=conn.id, asset=b.asset,
                free=b.free, locked=b.locked, total=b.total, reported_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_balances_connection_asset",
                set_={"free": b.free, "locked": b.locked, "total": b.total, "reported_at": now},
            )
        )
    # Ativos zerados deixam de aparecer na corretora.
    stale = select(Balance).where(Balance.connection_id == conn.id, Balance.asset.not_in(assets or {""}))
    for row in db.scalars(stale):
        db.delete(row)
    db.commit()
    return assets


def _sync_movements(db: Session, conn: ExchangeConnection, adapter: ExchangeAdapter, job: SyncJob, stats: dict) -> set[str]:
    assets: set[str] = set()
    caps = adapter.info.capabilities
    for kind, enabled in (("deposit", caps.deposits), ("withdrawal", caps.withdrawals)):
        if not enabled:
            continue
        cp = _checkpoint(db, conn, f"movements:{kind}")
        for _ in range(MAX_PAGES_PER_STREAM):
            page = adapter.fetch_movements(kind, cp.cursor)
            for m in page.items:
                assets.add(m.asset)
                db.execute(
                    insert(AssetMovement)
                    .values(
                        id=uuid.uuid4(), user_id=conn.user_id, connection_id=conn.id, kind=m.kind,
                        external_id=m.external_id, asset=m.asset, amount=m.amount, fee=m.fee,
                        network=m.network, tx_id=m.tx_id, status=m.status, occurred_at=m.occurred_at,
                        source="api", created_at=utcnow(),
                    )
                    .on_conflict_do_update(constraint="uq_asset_movements_external", set_={"status": m.status, "tx_id": m.tx_id})
                )
            stats[f"{kind}s"] = stats.get(f"{kind}s", 0) + len(page.items)
            cp.cursor = page.next_cursor
            cp.updated_at = utcnow()
            _heartbeat(db, job)
            db.commit()
            if not page.has_more:
                break
    return assets


def _sync_symbol(db: Session, conn: ExchangeConnection, adapter: ExchangeAdapter, symbol, job: SyncJob, stats: dict, events: dict) -> None:
    caps = adapter.info.capabilities
    if caps.orders:
        cp = _checkpoint(db, conn, f"orders:{symbol.symbol}")
        for _ in range(MAX_PAGES_PER_STREAM):
            page = adapter.fetch_orders(symbol, cp.cursor)
            ids = [o.external_id for o in page.items]
            previous = dict(
                db.execute(
                    select(ExchangeOrder.external_id, ExchangeOrder.status).where(
                        ExchangeOrder.connection_id == conn.id, ExchangeOrder.external_id.in_(ids)
                    )
                ).all()
            ) if ids else {}
            for o in page.items:
                values = dict(
                    status=o.status, executed_qty=o.executed_qty, cumulative_quote_qty=o.cumulative_quote_qty,
                    exchange_updated_at=o.updated_at, updated_at=utcnow(),
                )
                db.execute(
                    insert(ExchangeOrder)
                    .values(
                        id=uuid.uuid4(), user_id=conn.user_id, connection_id=conn.id, external_id=o.external_id,
                        market=symbol.market, symbol=symbol.symbol, base_asset=symbol.base_asset,
                        quote_asset=symbol.quote_asset, side=o.side, order_type=o.order_type, price=o.price,
                        orig_qty=o.orig_qty, placed_at=o.placed_at, created_at=utcnow(), **values,
                    )
                    .on_conflict_do_update(constraint="uq_exchange_orders_external", set_=values)
                )
                if o.status == "FILLED" and previous.get(o.external_id) != "FILLED":
                    events["filled_orders"].append(o)
            stats["orders"] = stats.get("orders", 0) + len(page.items)
            cp.cursor = page.next_cursor
            cp.updated_at = utcnow()
            _heartbeat(db, job)
            db.commit()
            if not page.has_more:
                break

    if caps.executions:
        cp = _checkpoint(db, conn, f"trades:{symbol.symbol}")
        for _ in range(MAX_PAGES_PER_STREAM):
            page = adapter.fetch_executions(symbol, cp.cursor)
            new_ids = insert_executions(db, conn, page.items)
            stats["executions_new"] = stats.get("executions_new", 0) + len(new_ids)
            stats["executions_seen"] = stats.get("executions_seen", 0) + len(page.items)
            events["new_execution_ids"].extend(new_ids)
            cp.cursor = page.next_cursor
            cp.updated_at = utcnow()
            _heartbeat(db, job)
            db.commit()
            if not page.has_more:
                break


def link_orders(db: Session, connection_id: uuid.UUID) -> None:
    db.execute(
        text(
            """
            UPDATE trade_executions te SET order_id = o.id
            FROM exchange_orders o
            WHERE te.connection_id = :cid AND te.order_id IS NULL
              AND o.connection_id = te.connection_id AND o.external_id = te.external_order_id
            """
        ),
        {"cid": connection_id},
    )


def take_snapshot(db: Session, conn: ExchangeConnection, base_currency: str) -> int:
    prices = CurrentPrices(db)
    now = utcnow()
    n = 0
    for b in db.scalars(select(Balance).where(Balance.connection_id == conn.id)):
        q = prices.get(b.asset, base_currency)
        db.add(
            BalanceSnapshot(
                user_id=conn.user_id, connection_id=conn.id, asset=b.asset, quantity=b.total,
                base_currency=base_currency, price=q.price if q else None,
                value=(b.total * q.price) if q else None, price_source=q.source if q else None,
                price_at=q.at if q else None, taken_at=now,
            )
        )
        n += 1
    db.commit()
    return n


def known_assets(db: Session, conn: ExchangeConnection) -> tuple[set[str], list[str]]:
    """Ativos e pares já vistos nesta conexão (para continuar sincronizando pares zerados)."""
    streams = db.scalars(
        select(SyncCheckpoint.stream).where(SyncCheckpoint.connection_id == conn.id, SyncCheckpoint.stream.like("trades:%"))
    ).all()
    symbols = [s.split(":", 1)[1] for s in streams]
    assets = set(db.scalars(select(AssetMovement.asset).where(AssetMovement.connection_id == conn.id).distinct()))
    return assets, symbols


# ------------------------------------------------------------------ execução
def _backoff_seconds(attempt: int, retry_after: float | None) -> int:
    base = min(3600, 30 * (2 ** max(0, attempt - 1)))
    return int(max(base, retry_after or 0))


def run_sync_job(db: Session, job: SyncJob, price_source: PriceSource | None = None) -> None:
    conn = db.get(ExchangeConnection, job.connection_id)
    if conn is None or conn.status == ConnectionStatus.SUSPENDED:
        job.status = "cancelled"
        job.finished_at = utcnow()
        job.error_message = "Conexão suspensa ou removida."
        db.commit()
        return
    user = db.get(User, conn.user_id)
    assert user is not None
    first_sync = conn.last_successful_sync_at is None
    stats: dict = {}
    events: dict = {"filled_orders": [], "new_execution_ids": []}
    adapter: ExchangeAdapter | None = None
    own_price_source = price_source is None
    started = utcnow()

    conn.status = ConnectionStatus.SYNCING
    conn.last_sync_at = started
    db.commit()
    try:
        creds = load_secret(db, owner_type=CONNECTION_OWNER, owner_id=conn.id, user_id=conn.user_id)
        if not creds:
            raise InvalidCredentials("Credencial não cadastrada.")
        adapter = build_adapter(conn.provider.key, creds, conn.settings)

        balance_assets = _sync_balances(db, conn, adapter)
        movement_assets = _sync_movements(db, conn, adapter, job, stats)
        prev_assets, prev_symbols = known_assets(db, conn)
        extra = list(conn.settings.get("extra_symbols") or []) + prev_symbols
        symbols = adapter.discover_symbols(balance_assets | movement_assets | prev_assets, extra)
        stats["symbols"] = len(symbols)
        for sym in symbols:
            _sync_symbol(db, conn, adapter, sym, job, stats, events)
        link_orders(db, conn.id)
        db.commit()

        if own_price_source:
            price_source = build_price_source()
        try:
            refresh_current_prices(db, price_source, balance_assets | {s.base_asset for s in symbols}, {user.base_currency})
        except TemporaryError as exc:
            stats["price_warning"] = redact_text(str(exc), 200)
            db.rollback()
        stats["snapshot_rows"] = take_snapshot(db, conn, user.base_currency)
        recalculate_user(db, user.id, price_source)

        conn = db.get(ExchangeConnection, job.connection_id)
        conn.status = ConnectionStatus.ACTIVE
        conn.status_message = None
        conn.last_successful_sync_at = utcnow()
        conn.consecutive_failures = 0
        job.status = "succeeded"
        job.finished_at = utcnow()
        job.error_message = None
        stats["duration_seconds"] = round((job.finished_at - started).total_seconds(), 2)
        job.stats = stats
        db.commit()
        log.info("sync_succeeded", extra={"job_id": str(job.id), "connection_id": str(conn.id), **stats})

        if not first_sync:
            _emit_sync_events(db, conn, events)
        notify.emit(
            db, conn.user_id, "sync_completed",
            f"✅ Sincronização concluída: {conn.name}. {stats.get('executions_new', 0)} nova(s) execução(ões).",
            {"connection_id": str(conn.id), **{k: v for k, v in stats.items() if isinstance(v, (int, float))}},
        )
        db.commit()

    except (InvalidCredentials, InsufficientPermissions) as exc:
        db.rollback()
        _fail(db, job, ConnectionStatus.INVALID_CREDENTIALS, str(exc), retry=False)
        notify.emit(db, job.user_id, "credential_invalid", f"🔑 Credencial inválida na conexão {conn.name}: {redact_text(str(exc), 200)}", {"connection_id": str(job.connection_id)})
        db.commit()
    except TemporaryError as exc:
        db.rollback()
        retry_after = exc.retry_after if isinstance(exc, RateLimited) else None
        _fail(db, job, ConnectionStatus.ERROR, str(exc), retry=True, retry_after=retry_after)
    except AdapterError as exc:
        db.rollback()
        _fail(db, job, ConnectionStatus.ERROR, str(exc), retry=False)
    except Exception as exc:  # noqa: BLE001 - falha inesperada não pode derrubar o worker
        db.rollback()
        log.exception("sync_unexpected_error", extra={"job_id": str(job.id)})
        _fail(db, job, ConnectionStatus.ERROR, f"Erro inesperado: {type(exc).__name__}", retry=True)
    finally:
        if adapter is not None:
            adapter.close()
        if own_price_source and price_source is not None and hasattr(price_source, "close"):
            price_source.close()


def _fail(db: Session, job: SyncJob, status: str, message: str, *, retry: bool, retry_after: float | None = None) -> None:
    s = get_settings()
    msg = redact_text(message, 500)
    job = db.get(SyncJob, job.id)
    conn = db.get(ExchangeConnection, job.connection_id)
    job.error_message = msg
    job.heartbeat_at = utcnow()
    if retry and job.attempts < job.max_attempts:
        job.status = "queued"
        job.locked_by = None
        job.run_after = utcnow() + timedelta(seconds=_backoff_seconds(job.attempts, retry_after))
    else:
        job.status = "failed"
        job.finished_at = utcnow()
    if conn:
        if conn.status != ConnectionStatus.SUSPENDED:
            conn.status = status
        conn.status_message = msg
        conn.last_error_at = utcnow()
        conn.consecutive_failures += 1
    db.commit()
    log.warning("sync_failed", extra={"job_id": str(job.id), "retry": job.status == "queued", "error": msg})
    if conn and status == ConnectionStatus.ERROR and conn.consecutive_failures in (s.failure_alert_threshold, s.failure_alert_threshold * 3):
        log.error("sync_repeated_failures", extra={"connection_id": str(conn.id), "failures": conn.consecutive_failures})
        notify.emit(
            db, conn.user_id, "integration_failure",
            f"⚠️ Falhas repetidas na integração {conn.name} ({conn.consecutive_failures} seguidas): {msg}",
            {"connection_id": str(conn.id), "failures": conn.consecutive_failures},
            dedupe_key=f"failure:{conn.id}:{conn.consecutive_failures}:{utcnow():%Y%m%d}",
        )
        db.commit()


def _fmt(d: Decimal) -> str:
    return f"{d.normalize():f}"


def _emit_sync_events(db: Session, conn: ExchangeConnection, events: dict) -> None:
    for o in events["filled_orders"][:20]:
        side = "Compra" if o.side == "BUY" else "Venda"
        notify.emit(
            db, conn.user_id, "order_filled",
            f"{'🟢' if o.side == 'BUY' else '🔴'} {side} detectada em {conn.name}: {_fmt(o.executed_qty)} {o.symbol.base_asset} "
            f"por {_fmt(o.cumulative_quote_qty)} {o.symbol.quote_asset} ({o.symbol.symbol}).",
            {"connection_id": str(conn.id), "order_id": o.external_id, "symbol": o.symbol.symbol},
            dedupe_key=f"order_filled:{conn.id}:{o.external_id}",
        )
    ids = events["new_execution_ids"]
    if ids:
        execs = db.scalars(select(TradeExecution).where(TradeExecution.id.in_(ids[:20]))).all()
        for e in execs:
            notify.emit(
                db, conn.user_id, "execution_new",
                f"Nova execução em {conn.name}: {'compra' if e.side == 'BUY' else 'venda'} de {_fmt(e.quantity)} "
                f"{e.base_asset} a {_fmt(e.price)} {e.quote_asset}.",
                {"connection_id": str(conn.id), "execution_id": str(e.id)},
                dedupe_key=f"execution_new:{e.id}",
            )
