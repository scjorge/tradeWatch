from __future__ import annotations

import json

import httpx
import respx
from sqlalchemy import select

from app.models import NotificationEvent
from app.modules.notifications import service as notify

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawZ"
TG = "https://api.telegram.org"


def _mock_bot(m, updates=None, send_ok=True):
    m.post(f"{TG}/bot{TOKEN}/getMe").mock(return_value=httpx.Response(200, json={"ok": True, "result": {"id": 42, "username": "tw_bot"}}))
    m.post(f"{TG}/bot{TOKEN}/getUpdates").mock(return_value=httpx.Response(200, json={"ok": True, "result": updates or []}))
    if send_ok:
        return m.post(f"{TG}/bot{TOKEN}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True, "result": {}}))
    return m.post(f"{TG}/bot{TOKEN}/sendMessage").mock(return_value=httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}))


def _create(api):
    return api.post("/api/notifications/channels/telegram", json={"name": "Meu Telegram", "bot_token": TOKEN})


def test_telegram_requires_destination_verification(make_user, db):
    api = make_user()
    with respx.mock(assert_all_called=False) as m:
        _mock_bot(m)
        r = _create(api)
        assert r.status_code == 201, r.text
        body = r.json()
        assert TOKEN not in json.dumps(body)
        assert body["channel"]["status"] == "pending_verification" and body["channel"]["token_hint"] == TOKEN[-4:]
        code = body["verification_code"]
        cid = body["channel"]["id"]
        # sem código no chat: não verifica e não aceita destino arbitrário
        assert api.post(f"/api/notifications/channels/{cid}/verify").status_code == 400
        assert api.post(f"/api/notifications/channels/{cid}/test").status_code == 400

    updates = [{"update_id": 1, "message": {"text": f"/start {code}", "chat": {"id": 777, "type": "private", "first_name": "Ana"}}}]
    with respx.mock(assert_all_called=False) as m:
        send = _mock_bot(m, updates)
        r = api.post(f"/api/notifications/channels/{cid}/verify")
        assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["enabled"]
        assert api.post(f"/api/notifications/channels/{cid}/test").status_code == 200
        assert json.loads(send.calls[-1].request.content)["chat_id"] == 777


def test_outbox_delivery_dedupe_and_redaction(make_user, db):
    api = make_user()
    with respx.mock(assert_all_called=False) as m:
        _mock_bot(m)
        body = _create(api).json()
    code, cid = body["verification_code"], body["channel"]["id"]
    updates = [{"update_id": 1, "message": {"text": code, "chat": {"id": -100, "type": "group", "title": "Trades"}}}]
    with respx.mock(assert_all_called=False) as m:
        _mock_bot(m, updates)
        api.post(f"/api/notifications/channels/{cid}/verify")

    from app.models import User

    user = db.scalar(select(User))
    assert notify.emit(db, user.id, "order_filled", "Compra detectada", dedupe_key="o1") == 1
    assert notify.emit(db, user.id, "order_filled", "Compra detectada", dedupe_key="o1") == 0
    # sync_completed vem desativado por padrão
    assert notify.emit(db, user.id, "sync_completed", "ok") == 0
    db.commit()

    with respx.mock(assert_all_called=False) as m:
        _mock_bot(m, send_ok=False)
        notify.deliver_pending(db)
    ev = db.scalar(select(NotificationEvent).where(NotificationEvent.event_type == "order_filled"))
    db.refresh(ev)
    assert ev.status == "failed"  # 403 é permanente
    assert TOKEN not in (ev.error or "") and "blocked" in ev.error
    hist = api.get("/api/notifications/events").json()
    assert hist["total"] >= 1 and TOKEN not in json.dumps(hist)


def test_network_error_does_not_leak_token(make_user):
    api = make_user()
    with respx.mock(assert_all_called=False) as m:
        m.post(f"{TG}/bot{TOKEN}/getMe").mock(side_effect=httpx.ConnectError(f"falhou {TG}/bot{TOKEN}/getMe"))
        r = _create(api)
    assert r.status_code == 400
    assert TOKEN not in r.text


def test_preferences_roundtrip(make_user):
    api = make_user()
    prefs = api.get("/api/notifications/preferences").json()
    assert {p["event_type"] for p in prefs} >= {"order_filled", "daily_summary", "equity_change"}
    r = api.put(
        "/api/notifications/preferences",
        json={"items": [{"event_type": "equity_change", "enabled": True, "settings": {"threshold_pct": 2.5}}, {"event_type": "daily_summary", "enabled": False, "settings": {"hour": 8}}]},
    )
    assert r.status_code == 200
    by = {p["event_type"]: p for p in r.json()}
    assert by["equity_change"]["settings"]["threshold_pct"] == 2.5
    assert by["daily_summary"]["enabled"] is False
    bad = api.put("/api/notifications/preferences", json={"items": [{"event_type": "daily_summary", "enabled": True, "settings": {"hour": 30}}]})
    assert bad.status_code == 400
