from __future__ import annotations

import base64
import json
import logging

import pytest
from sqlalchemy import select

from app.core.crypto import CredentialVault, VaultError, set_vault
from app.integrations import registry
from app.models import EncryptedCredential
from tests import fakes


def _create(api, name="Minha Binance", secret=fakes.GOOD_SECRET):
    return api.post(
        "/api/integrations/connections",
        json={"provider": "binance", "name": name, "credentials": {"api_key": fakes.GOOD_KEY, "api_secret": secret}},
    )


def test_users_cannot_see_or_touch_each_other(make_user):
    fakes.install(registry)
    ana, beto = make_user("ana@example.com"), make_user("beto@example.com")
    r = _create(ana)
    assert r.status_code == 201, r.text
    cid = r.json()["connection"]["id"]

    assert beto.get("/api/integrations/connections").json() == []
    for method, url in [
        ("get", f"/api/integrations/connections/{cid}"),
        ("patch", f"/api/integrations/connections/{cid}"),
        ("post", f"/api/integrations/connections/{cid}/sync"),
        ("post", f"/api/integrations/connections/{cid}/suspend"),
        ("get", f"/api/integrations/connections/{cid}/jobs"),
        ("delete", f"/api/integrations/connections/{cid}"),
    ]:
        kw = {"json": {"name": "x"}} if method == "patch" else {}
        resp = getattr(beto, method)(url, **kw)
        assert resp.status_code == 404, (method, url, resp.status_code)

    # filtro por connection_id de outro usuário não vaza dados
    r = beto.get(f"/api/trades/executions?connection_id={cid}")
    assert r.status_code == 200 and r.json()["total"] == 0
    assert ana.get(f"/api/integrations/connections/{cid}").status_code == 200


def test_secret_never_returned_and_stored_encrypted(make_user, db):
    fakes.install(registry)
    ana = make_user()
    r = _create(ana)
    body = json.dumps(r.json())
    assert fakes.GOOD_SECRET not in body and fakes.GOOD_KEY not in body
    assert r.json()["connection"]["credential_hint"] == "…AAAA"
    listed = json.dumps(ana.get("/api/integrations/connections").json())
    assert fakes.GOOD_SECRET not in listed

    row = db.scalar(select(EncryptedCredential))
    assert fakes.GOOD_SECRET.encode() not in row.ciphertext
    assert row.key_version == 1


def test_invalid_credentials_marked_and_not_synced(make_user):
    fakes.install(registry)
    ana = make_user()
    r = _create(ana, secret="errado" * 10)
    assert r.status_code == 201
    assert r.json()["connection"]["status"] == "invalid_credentials"
    assert r.json()["validation"]["ok"] is False
    cid = r.json()["connection"]["id"]
    assert ana.post(f"/api/integrations/connections/{cid}/sync").status_code == 400
    # substituir a credencial revalida
    r = ana.put(f"/api/integrations/connections/{cid}/credentials", json={"credentials": {"api_key": fakes.GOOD_KEY, "api_secret": fakes.GOOD_SECRET}})
    assert r.json()["connection"]["status"] == "active"


def test_admin_cannot_read_credentials(make_user, db):
    from app.cli import create_admin

    fakes.install(registry)
    ana = make_user("ana@example.com")
    _create(ana)
    admin = make_user("root@example.com")
    create_admin(db, "root@example.com", None)
    r = admin.get("/api/admin/users")
    assert r.status_code == 200
    assert fakes.GOOD_SECRET not in r.text and fakes.GOOD_KEY not in r.text
    # rota de dados do usuário continua isolada mesmo para admin
    assert admin.get("/api/integrations/connections").json() == []
    # usuário comum não acessa administração
    assert ana.get("/api/admin/users").status_code == 403


def test_vault_aad_binds_owner_and_rotation():
    k1, k2 = b"1" * 32, b"2" * 32
    v1 = CredentialVault({1: k1})
    blob = v1.encrypt({"s": "x"}, owner_type="t", owner_id="a", user_id="u")
    assert v1.decrypt(blob, owner_type="t", owner_id="a", user_id="u") == {"s": "x"}
    with pytest.raises(VaultError):
        v1.decrypt(blob, owner_type="t", owner_id="OUTRO", user_id="u")
    v2 = CredentialVault({1: k1, 2: k2}, active_version=2)
    assert v2.decrypt(blob, owner_type="t", owner_id="a", user_id="u") == {"s": "x"}
    assert v2.encrypt({"s": "y"}, owner_type="t", owner_id="a", user_id="u").key_version == 2


def test_rotate_all_reencrypts(make_user, db):
    from app.core.credentials import load_secret, rotate_all
    from app.core.crypto import get_vault

    fakes.install(registry)
    ana = make_user()
    cid = _create(ana).json()["connection"]["id"]
    old = get_vault()
    try:
        set_vault(CredentialVault({1: b"k" * 32, 2: b"z" * 32}, active_version=2))
        assert rotate_all(db) == 1
        row = db.scalar(select(EncryptedCredential))
        db.refresh(row)
        assert row.key_version == 2
        import uuid

        assert load_secret(db, owner_type="exchange_connection", owner_id=uuid.UUID(cid), user_id=row.user_id)["api_secret"] == fakes.GOOD_SECRET
    finally:
        set_vault(old)


def test_logs_are_redacted(caplog):
    from app.core.logging import JsonFormatter

    rec = logging.LogRecord("x", logging.INFO, "", 0, "url https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/getMe signature=abc123", (), None)
    rec.api_secret = "segredo"
    out = JsonFormatter().format(rec)
    assert "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw" not in out
    assert "abc123" not in out and "segredo" not in out


def test_parse_keys_rejects_short_key():
    from app.core.crypto import parse_keys

    with pytest.raises(VaultError):
        parse_keys("1:" + base64.b64encode(b"curta").decode())
