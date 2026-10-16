"""Operações compra → venda: cada compra casada (FIFO) com a venda que a encerrou, valores em BRL e filtros."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.modules.trades.cycles import Exec, build_cycles
from tests import fakes
from tests.test_sync import _run_all, _setup

DAY = 24 * 60
NOON = 12 * 60  # evita virada de dia no fuso do usuário (America/Sao_Paulo)


def _rows(api, **params):
    return api.get("/api/trades/cycles", params=params).json()["items"]


def test_synced_executions_become_buy_sell_rows(make_user, db):
    execs = [fakes.ex(1, "BUY", "1", "50000", fee="50"), fakes.ex(2, "SELL", "0.5", "60000", fee="30")]
    api, state, cid = _setup(make_user, db, execs)
    _run_all(db)
    rows = {c["status"]: c for c in _rows(api)}
    closed, opened = rows["closed"], rows["open"]
    assert closed["status_label"] == "Concluído" and opened["status_label"] == "Ativo"
    # câmbio histórico USDT/BRL simulado = 5; metade do lote, com a taxa paga em USDT
    assert D(closed["buy_quantity"]) == D("0.5") and D(closed["buy_price"]) == D("50000")
    assert D(closed["buy_total"]) == D("25000") and D(closed["buy_unit_brl"]) == D("250000")
    assert D(closed["buy_total_brl"]) == (D("25000") + D("25")) * 5
    assert D(closed["sell_total"]) == D("30000") - D("30")
    assert D(closed["sell_total_brl"]) == (D("30000") - D("30")) * 5
    assert D(closed["pnl_brl"]) == D("4945") * 5
    assert D(closed["fees_brl"]) == (D("25") + D("30")) * 5  # metade da taxa da compra + taxa da venda
    assert abs(closed["pnl_pct"] - float(D("24725") / D("125125") * 100)) < 1e-9
    assert closed["account"] == "Minha Binance" and closed["source"] == "api"
    # posição em aberto estimada pela cotação atual (BTC 60.000, USDT/BRL 5)
    assert D(opened["sell_quantity"]) == D("0.5") and opened["estimated"]
    assert D(opened["pnl_brl"]) == D("0.5") * 60000 * 5 - (D("25000") + D("25")) * 5


def test_filters_summary_and_calendar(make_user, db):
    execs = [
        fakes.ex(1, "BUY", "1", "100", minutes=NOON),
        fakes.ex(2, "SELL", "1", "110", minutes=NOON + 3 * DAY),  # +10 USDT = +50 BRL, 3 dias
        fakes.ex(3, "BUY", "1", "100", minutes=NOON + 10 * DAY),
        fakes.ex(4, "SELL", "1", "95", minutes=NOON + 20 * DAY),  # −25 BRL, 10 dias
        fakes.ex(5, "BUY", "1", "100", minutes=NOON + 30 * DAY),
        fakes.ex(6, "SELL", "1", "120", minutes=NOON + 32 * DAY),  # +100 BRL, 2 dias (fevereiro)
    ]
    api, state, cid = _setup(make_user, db, execs)
    _run_all(db)
    s = api.get("/api/trades/cycles/summary").json()
    assert s["closed_count"] == 3 and s["wins"] == 2 and s["losses"] == 1
    assert D(s["pnl_brl"]) == 125 and D(s["gains_brl"]) == 150 and D(s["losses_brl"]) == -25
    assert s["profit_factor"] == 6.0 and s["payoff_ratio"] == 3.0
    assert [(p["period"], p["pnl_brl"], p["cumulative_brl"]) for p in s["periods"]] == [("2026-01", "25", "25"), ("2026-02", "100", "125")]
    assert s["periods"][1]["change_vs_prev_brl"] == "75"
    assert s["by_asset"][0]["asset"] == "BTC"

    assert len(_rows(api, result="loss")) == 1
    assert len(_rows(api, result="gain")) == 2
    assert len(_rows(api, min_pnl="60")) == 1
    assert len(_rows(api, max_pct="0")) == 1
    assert len(_rows(api, min_days="5")) == 1
    assert len(_rows(api, start=datetime(2026, 2, 1, tzinfo=UTC).isoformat())) == 1
    assert [c["pnl_brl"] for c in _rows(api, sort="pnl_brl", direction="asc")] == ["-25", "50", "100"]
    assert len(_rows(api, status="closed")) == 3

    cal = api.get("/api/trades/cycles/calendar?month=2026-01").json()
    assert len(cal["days"]) == 31 and cal["total_brl"] == "25"
    assert next(d for d in cal["days"] if d["date"] == "2026-01-04")["pnl_brl"] == "50"

    csv_text = api.get("/api/trades/cycles.csv").text
    assert csv_text.splitlines()[0].startswith("Status;Criptomoeda;Moeda;Conta;Data Compra;Quant. a Comprar")
    assert len(csv_text.splitlines()) == 4
    assert "Taxa BRL" in csv_text.splitlines()[0]


def test_users_only_see_their_own_rows(make_user, db):
    api, state, cid = _setup(make_user, db, [fakes.ex(1, "BUY", "1", "100"), fakes.ex(2, "SELL", "1", "110")])
    _run_all(db)
    other = make_user("beto@example.com")
    assert _rows(other) == []
    assert other.get("/api/trades/cycles/summary").json()["closed_count"] == 0
    assert len(_rows(api)) == 1


def test_manual_entry_endpoints_do_not_exist(make_user):
    api = make_user()
    assert api.post("/api/trades/manual", json={}).status_code in (404, 405)
    assert api.post("/api/trades/import-sheet", json={}).status_code in (404, 405)


# ------------------------------------------------------------------ cálculo puro
T = datetime(2026, 1, 1, tzinfo=UTC)


def _ex(i, side, qty, price, fee="0", fee_asset=None):
    return Exec(uuid.uuid4(), None, T + timedelta(hours=i), "BTC", "USDT", side, D(qty), D(price), D(fee), fee_asset)


def _fx(asset, at):
    return {"USDT": D(5), "BNB": D(2500)}.get(asset)


def test_fifo_slices_partial_sale_and_shortfall():
    b1, b2 = _ex(1, "BUY", "1", "100"), _ex(2, "BUY", "1", "200")
    s = _ex(3, "SELL", "1.5", "300")
    cycles = build_cycles([b1, b2, s], _fx)
    closed = [c for c in cycles if c.status == "closed"]
    assert [(c.buy_execution_id, c.sell_quantity) for c in closed] == [(b1.id, D(1)), (b2.id, D("0.5"))]
    assert [c.pnl_brl for c in closed] == [D(1000), D(250)]  # (300−100)×5 ; 0,5×(300−200)×5
    [op] = [c for c in cycles if c.status == "open"]
    assert op.sell_quantity == D("0.5") and op.buy_execution_id == b2.id

    orphan = build_cycles([_ex(1, "SELL", "1", "10")], _fx)
    assert orphan[0].complete is False and orphan[0].pnl_brl is None and "Sem compra" in orphan[0].note


def test_fee_in_asset_reduces_quantity_to_sell():
    buy = _ex(1, "BUY", "334.14", "0.08675", fee="0.33414", fee_asset="BTC")
    sell = _ex(2, "SELL", "333.80586", "0.08821")
    [c] = build_cycles([buy, sell], _fx)
    assert c.buy_quantity == D("334.14") and c.buy_fee == D("0.33414") and c.sell_quantity == D("333.80586")
    assert c.buy_total_brl == D("28.986645") * 5
    assert c.pnl_brl == (D("0.08821") * D("333.80586") - D("28.986645")) * 5


def test_bnb_fee_added_to_cost():
    buy = _ex(1, "BUY", "1", "100", fee="0.01", fee_asset="BNB")
    sell = _ex(2, "SELL", "1", "100")
    [c] = build_cycles([buy, sell], _fx)
    assert c.buy_total_brl == D(500) + D(25) and c.pnl_brl == D(-25) and c.fees_brl == D(25)


def test_missing_fx_marks_incomplete():
    [c] = build_cycles([_ex(1, "BUY", "1", "100"), _ex(2, "SELL", "1", "110")], lambda a, t: None)
    assert c.complete is False and c.pnl_brl is None and "Câmbio" in c.note
