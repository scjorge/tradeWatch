from __future__ import annotations

from app.core.origins import origin_allowed
from tests.conftest import PASSWORD

BASE = "http://localhost:8080"


def test_same_origin_as_host_is_allowed():
    assert origin_allowed("http://192.168.0.10:8080", "192.168.0.10:8080", "http", BASE)
    assert origin_allowed("http://127.0.0.1:8080", "127.0.0.1:8080", "http", BASE)
    # HTTPS na borda (Traefik) e http entre proxies: a porta padrão vem do esquema da origem
    assert origin_allowed("https://trade.exemplo.com", "trade.exemplo.com", "http", "https://trade.exemplo.com")


def test_configured_origins_and_rejections():
    assert origin_allowed(None, "x", "http", BASE)
    assert origin_allowed("http://localhost:8080", "api:8000", "http", BASE)
    assert origin_allowed("http://meu-pc:8080", "api:8000", "http", BASE, "http://meu-pc:8080, http://outro")
    assert not origin_allowed("https://evil.example", "localhost:8080", "http", BASE)
    assert not origin_allowed("http://localhost:9999", "localhost:8080", "http", BASE)
    assert not origin_allowed("null", "localhost:8080", "http", BASE)


def test_register_respects_origin(anon):
    body = {"email": "ana@example.com", "password": PASSWORD}
    # TestClient usa Host "testserver"
    assert anon.post("/api/auth/register", json=body, headers={"Origin": "http://testserver"}).status_code == 202
    r = anon.post("/api/auth/register", json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"
