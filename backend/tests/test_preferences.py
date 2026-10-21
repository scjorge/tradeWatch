"""Preferências de interface salvas no perfil do usuário (não no navegador)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import PASSWORD, Api

COLS = ["status", "asset", "fees_brl", "pnl_brl"]


def test_columns_saved_in_profile_follow_the_user(make_user):
    from app.main import app

    api = make_user()
    assert api.get("/api/me/modules/trades/settings").json()["settings"] == {}
    r = api.patch("/api/me/modules/trades/settings", json={"settings": {"buysell_columns": COLS}})
    assert r.status_code == 200 and r.json()["settings"]["buysell_columns"] == COLS

    # outro "dispositivo": nova sessão, sem nada no navegador
    other = Api(TestClient(app))
    other.c.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert other.get("/api/me/modules/trades/settings").json()["settings"]["buysell_columns"] == COLS

    # mescla chaves e remove com null
    api.patch("/api/me/modules/trades/settings", json={"settings": {"outra": 1}})
    s = api.get("/api/me/modules/trades/settings").json()["settings"]
    assert s == {"buysell_columns": COLS, "outra": 1}
    api.patch("/api/me/modules/trades/settings", json={"settings": {"outra": None}})
    assert api.get("/api/me/modules/trades/settings").json()["settings"] == {"buysell_columns": COLS}


def test_preferences_are_per_user_and_validated(make_user):
    ana, beto = make_user("ana@example.com"), make_user("beto@example.com")
    ana.patch("/api/me/modules/trades/settings", json={"settings": {"buysell_columns": COLS}})
    assert beto.get("/api/me/modules/trades/settings").json()["settings"] == {}
    assert ana.patch("/api/me/modules/trades/settings", json={"settings": {"Chave Inválida!": 1}}).status_code == 400
    assert ana.patch("/api/me/modules/trades/settings", json={"settings": {"grande": "x" * 20000}}).status_code == 400
    assert ana.get("/api/me/modules/inexistente/settings").status_code == 404
    # CSRF continua obrigatório
    assert ana.c.patch("/api/me/modules/trades/settings", json={"settings": {}}).status_code == 403


def test_global_filters_saved_in_core_module(make_user):
    api = make_user()
    filters = {"period": "custom", "range": ["2026-01-05", "2026-01-20"], "connectionIds": [], "asset": "BTC", "side": "", "market": "", "provider": ""}
    assert api.patch("/api/me/modules/core/settings", json={"settings": {"global_filters": filters}}).status_code == 200
    assert api.get("/api/me/modules/core/settings").json()["settings"]["global_filters"] == filters


def test_delete_own_account_requires_password(make_user):
    api = make_user("apagar@example.com")
    assert api.post("/api/me/delete", json={"password": "errada"}).status_code == 400
    assert api.get("/api/me").status_code == 200
    assert api.post("/api/me/delete", json={"password": PASSWORD}).status_code == 204
    assert api.get("/api/me").status_code == 401
    other = Api(TestClient(__import__("app.main", fromlist=["app"]).app))
    assert other.c.post("/api/auth/login", json={"email": "apagar@example.com", "password": PASSWORD}).status_code in (400, 401)
