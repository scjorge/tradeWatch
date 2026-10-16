from __future__ import annotations

from sqlalchemy import select

from app.core.mailer import OUTBOX
from app.models import AuditLog, User
from tests.conftest import PASSWORD, Api, last_link_token


def test_register_requires_verification_then_login(anon):
    r = anon.post("/api/auth/register", json={"email": "Bia@Example.com", "password": PASSWORD})
    assert r.status_code == 202
    r = anon.post("/api/auth/login", json={"email": "bia@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    assert anon.post("/api/auth/verify-email", json={"token": last_link_token()}).status_code == 200
    r = anon.post("/api/auth/login", json={"email": "bia@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["email"] == "bia@example.com"
    cookie = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookie if c.startswith("tw_session="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert anon.get("/api/me").status_code == 200


def test_register_existing_email_is_indistinguishable(anon, make_user):
    make_user("ana@example.com")
    r = anon.post("/api/auth/register", json={"email": "ana@example.com", "password": PASSWORD})
    assert r.status_code == 202
    assert "já possui conta" in OUTBOX[-1].get_content()


def test_weak_password_rejected(anon):
    r = anon.post("/api/auth/register", json={"email": "x@example.com", "password": "curta"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "weak_password"


def test_lockout_after_repeated_failures(anon, make_user, db):
    make_user("ana@example.com")
    for _ in range(5):
        r = anon.post("/api/auth/login", json={"email": "ana@example.com", "password": "errada-XYZ-1"})
        assert r.status_code == 401
    r = anon.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "account_locked"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.account_locked")) is not None


def test_csrf_required_for_mutations(make_user):
    api = make_user()
    r = api.c.patch("/api/me", json={"display_name": "Sem CSRF"})
    assert r.status_code == 403
    r = api.patch("/api/me", json={"display_name": "Com CSRF"})
    assert r.status_code == 200 and r.json()["display_name"] == "Com CSRF"


def test_form_posts_are_rejected(anon):
    r = anon.post("/api/auth/login", content="email=a&password=b", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def test_logout_revokes_session(make_user):
    api = make_user()
    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/me").status_code == 401


def test_password_reset_revokes_all_sessions(make_user, anon):
    api = make_user()
    assert anon.post("/api/auth/forgot-password", json={"email": "ana@example.com"}).status_code == 202
    token = last_link_token()
    new = "Outra-Senha-456"
    assert anon.post("/api/auth/reset-password", json={"token": token, "new_password": new}).status_code == 200
    assert api.get("/api/me").status_code == 401
    # token é de uso único
    assert anon.post("/api/auth/reset-password", json={"token": token, "new_password": new}).status_code == 400
    assert anon.post("/api/auth/login", json={"email": "ana@example.com", "password": new}).status_code == 200


def test_forgot_password_unknown_email_same_response(anon):
    r = anon.post("/api/auth/forgot-password", json={"email": "ninguem@example.com"})
    assert r.status_code == 202 and not OUTBOX


def test_change_password_keeps_current_and_revokes_others(make_user):
    from app.main import app
    from fastapi.testclient import TestClient

    api = make_user()
    other = TestClient(app)
    other.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert other.get("/api/me").status_code == 200
    r = api.post("/api/me/password", json={"current_password": "errada", "new_password": "Nova-Senha-789"})
    assert r.status_code == 400
    r = api.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "Nova-Senha-789"})
    assert r.status_code == 204
    assert api.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401


def test_sessions_list_and_revoke(make_user):
    from app.main import app
    from fastapi.testclient import TestClient

    api = make_user()
    other = Api(TestClient(app))
    other.c.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    sessions = api.get("/api/me/sessions").json()
    assert len(sessions) == 2
    target = next(s for s in sessions if not s["current"])
    assert api.delete(f"/api/me/sessions/{target['id']}").status_code == 204
    assert other.get("/api/me").status_code == 401


def test_password_hash_is_argon2id(make_user, db):
    make_user()
    user = db.scalar(select(User))
    assert user.password_hash.startswith("$argon2id$")
