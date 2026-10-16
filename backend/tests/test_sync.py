from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.integrations import registry
from app.integrations.base import InvalidCredentials, MovementDTO, RateLimited
from app.models import Balance, BalanceSnapshot, ExchangeConnection, SyncCheckpoint, SyncJob, TradeExecution
from app.models.base import utcnow
from app.modules.trades.sync import claim_next_job, requeue_stale_jobs, run_sync_job
from tests import fakes
from tests.test_isolation_and_credentials import _create


def _run_all(db, max_jobs=10):
    for _ in range(max_jobs):
        db.execute(SyncJob.__table__.update().where(SyncJob.status == "queued").values(run_after=utcnow() - timedelta(seconds=1)))
        db.commit()
        job = claim_next_job(db, "test")
        if job is None:
            return
        run_sync_job(db, job, fakes.FakePrices())


def _setup(make_user, db, executions):
    state = fakes.install(registry)
    state.executions = executions
    api = make_user()
    cid = _create(api).json()["connection"]["id"]
    return api, state, uuid.UUID(cid)


def test_sync_is_idempotent(make_user, db):
    api, state, cid = _setup(make_user, db, [fakes.ex(1, "BUY", "1", "50000"), fakes.ex(2, "SELL", "0.5", "60000"), fakes.ex(3, "BUY", "0.1", "55000")])
    _run_all(db)
    assert db.scalar(select(func.count()).select_from(TradeExecution)) == 3

    # Nova sincronização reprocessando desde o início não duplica nada
    db.execute(SyncCheckpoint.__table__.delete())
    db.commit()
    api.post(f"/api/integrations/connections/{cid}/sync")
    _run_all(db)
    assert db.scalar(select(func.count()).select_from(TradeExecution)) == 3

    conn = db.get(ExchangeConnection, cid)
    db.refresh(conn)
    assert conn.status == "active" and conn.last_successful_sync_at is not None
    assert db.scalar(select(func.count()).select_from(Balance)) == 2
    assert db.scalar(select(func.count()).select_from(BalanceSnapshot)) >= 2

    data = api.get("/api/trades/executions?sort=price&direction=asc").json()
    assert data["total"] == 3
    assert [i["price"] for i in data["items"]] == ["50000", "55000", "60000"]


def test_sync_resumes_after_failure_without_duplicates(make_user, db):
    execs = [fakes.ex(i, "BUY", "0.1", "50000") for i in range(1, 6)]
    api, state, cid = _setup(make_user, db, execs)
    state.fail_on_call = 2  # falha na segunda página
    _run_all(db, max_jobs=1)
    job = db.scalar(select(SyncJob))
    assert job.status == "queued" and job.attempts == 1  # reprogramado com backoff
    assert job.run_after > utcnow()
    assert db.scalar(select(func.count()).select_from(TradeExecution)) == 2  # primeira página persistida
    cp = db.scalar(select(SyncCheckpoint).where(SyncCheckpoint.stream == "trades:BTCUSDT"))
    assert cp.cursor == {"from": 2}
    conn = db.get(ExchangeConnection, cid)
    assert conn.status == "error"

    _run_all(db)
    assert db.scalar(select(func.count()).select_from(TradeExecution)) == 5
    db.refresh(conn)
    assert conn.status == "active" and conn.consecutive_failures == 0


def test_rate_limit_respects_retry_after(make_user, db):
    api, state, cid = _setup(make_user, db, [fakes.ex(1, "BUY", "1", "50000")])
    state.fail_on_call = 1
    state.fail_with = RateLimited("limite", retry_after=900)
    _run_all(db, max_jobs=1)
    job = db.scalar(select(SyncJob))
    assert job.status == "queued"
    assert job.run_after >= utcnow() + timedelta(seconds=850)


def test_invalid_credentials_during_sync_stops_retries(make_user, db):
    api, state, cid = _setup(make_user, db, [fakes.ex(1, "BUY", "1", "50000")])
    state.fail_on_call = 1
    state.fail_with = InvalidCredentials("revogada")
    _run_all(db, max_jobs=1)
    job = db.scalar(select(SyncJob))
    assert job.status == "failed"
    assert db.get(ExchangeConnection, cid).status == "invalid_credentials"


def test_stale_running_job_is_requeued(make_user, db):
    api, state, cid = _setup(make_user, db, [])
    job = claim_next_job(db, "worker-morto")
    job.heartbeat_at = utcnow() - timedelta(hours=1)
    db.commit()
    assert requeue_stale_jobs(db) == 1
    db.refresh(job)
    assert job.status == "queued"


def test_suspend_cancels_and_blocks_sync(make_user, db):
    api, state, cid = _setup(make_user, db, [])
    r = api.post(f"/api/integrations/connections/{cid}/suspend")
    assert r.json()["status"] == "suspended"
    assert db.scalar(select(SyncJob)).status == "cancelled"
    assert api.post(f"/api/integrations/connections/{cid}/sync").status_code == 400
    r = api.post(f"/api/integrations/connections/{cid}/resume")
    assert r.status_code == 200
    _run_all(db)
    assert db.get(ExchangeConnection, cid).status == "active"


def test_pnl_after_sync_and_dashboard(make_user, db):
    execs = [
        fakes.ex(1, "BUY", "1", "50000", fee="50"),
        fakes.ex(2, "SELL", "0.5", "60000", fee="30"),
    ]
    api, state, cid = _setup(make_user, db, execs)
    state.movements = [MovementDTO("deposit", "d1", "USDT", Decimal("50000"), Decimal(0), "TRX", "tx1", "completed", fakes.T0 - timedelta(days=1))]
    _run_all(db)
    s = api.get("/api/trades/pnl/summary").json()
    # custo de 0.5 BTC = (50000 + 50) / 2 = 25025 ; receita = 30000 - 30 = 29970
    assert Decimal(s["realized_net"]) == Decimal("4945")
    assert Decimal(s["fees_paid"]) == Decimal("80")
    assert s["closed_operations"] == 1 and s["win_rate_pct"] == 100.0
    d = api.get("/api/dashboard").json()
    assert d["holdings"]["total_value"] is not None
    assert d["integrations"][0]["status"] == "active"
    pos = api.get("/api/trades/positions").json()
    btc = next(p for p in pos["positions"] if p["asset"] == "BTC")
    assert Decimal(btc["quantity"]) == Decimal("0.5") and Decimal(btc["cost_basis"]) == Decimal("25025")
    assert Decimal(btc["unrealized_pnl"]) == Decimal("0.5") * 60000 - Decimal("25025")
    # depósito não é lucro
    assert all(Decimal(r["realized_pnl"] or 0) != Decimal("50000") for r in api.get("/api/trades/pnl/realized").json()["items"])


def test_filters_and_csv_export(make_user, db):
    execs = [fakes.ex(1, "BUY", "1", "50000"), fakes.ex(2, "SELL", "0.5", "60000", minutes=60 * 24 * 3)]
    api, state, cid = _setup(make_user, db, execs)
    _run_all(db)
    assert api.get("/api/trades/executions?side=SELL").json()["total"] == 1
    assert api.get("/api/trades/executions?asset=ETH").json()["total"] == 0
    assert api.get("/api/trades/executions?min_value=40000").json()["total"] == 1
    start = (fakes.T0 + timedelta(days=1)).isoformat()
    assert api.get("/api/trades/executions", params={"start": start}).json()["total"] == 1
    assert api.get("/api/trades/executions?q=BTC").json()["total"] == 2
    r = api.get("/api/trades/executions.csv")
    assert r.status_code == 200 and r.text.count("\n") == 3
    assert "BTCUSDT" in r.text


def test_sync_all_queues_eligible_connections_only(make_user, db):
    api, state, cid = _setup(make_user, db, [fakes.ex(1, "BUY", "1", "50000")])
    other = _create(api, name="Outra").json()["connection"]["id"]
    api.post(f"/api/integrations/connections/{other}/suspend")
    _run_all(db)  # consome o job inicial

    r = api.post("/api/integrations/sync-all")
    assert r.status_code == 202
    body = r.json()
    assert [q["id"] for q in body["queued"]] == [str(cid)] and body["queued"][0]["job_id"] != "None"
    assert [s["id"] for s in body["skipped"]] == [other]
    # chamar de novo não duplica o job na fila
    assert api.post("/api/integrations/sync-all").json()["queued"][0]["job_id"] == body["queued"][0]["job_id"]
    _run_all(db)
    assert db.get(ExchangeConnection, cid).status == "active"
