"""Infraestrutura de testes.

Requer um PostgreSQL descartável em ``TEST_DATABASE_URL``. Nenhuma chave real de
corretora ou Telegram é necessária: as integrações são simuladas.
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Iterator

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.exit("Defina TEST_DATABASE_URL apontando para um banco PostgreSQL descartável.", returncode=2)

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": TEST_DB,
        "COOKIE_SECURE": "false",
        "REQUIRE_EMAIL_VERIFICATION": "true",
        "CREDENTIALS_KEYS": "1:" + base64.b64encode(b"k" * 32).decode(),
        "LOG_LEVEL": "WARNING",
        "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.mailer import OUTBOX  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.db import Base, configure_engine, session_factory  # noqa: E402
from app.integrations import registry  # noqa: E402
from app.modules.notifications import telegram  # noqa: E402

configure_engine(TEST_DB)


def _alembic_cfg() -> Config:
    here = os.path.dirname(os.path.dirname(__file__))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with session_factory()() as db:
        db.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        db.commit()
    command.upgrade(_alembic_cfg(), "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    from app.cli import seed

    with session_factory()() as db:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.commit()
        seed(db)
    OUTBOX.clear()
    limiter.reset()
    # Nunca acessa a internet nos testes: fonte de preços simulada por padrão.
    from tests.fakes import FakePrices

    registry.set_factories(None, lambda: FakePrices())
    telegram.set_factory(None)
    yield


@pytest.fixture
def db():
    with session_factory()() as s:
        yield s


@pytest.fixture
def alembic_cfg() -> Config:
    return _alembic_cfg()


class Api:
    """Cliente autenticado que envia o cabeçalho CSRF automaticamente."""

    def __init__(self, client: TestClient):
        self.c = client

    def _headers(self, kw):
        h = dict(kw.pop("headers", {}) or {})
        csrf = self.c.cookies.get("tw_csrf")
        if csrf:
            h["X-CSRF-Token"] = csrf
        return h

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self._headers(kw), **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self._headers(kw), **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self._headers(kw), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._headers(kw), **kw)


PASSWORD = "Senha-Forte-123"


def last_link_token() -> str:
    body = OUTBOX[-1].get_content()
    return re.search(r"#t=([A-Za-z0-9_\-]+)", body).group(1)


@pytest.fixture
def make_user() -> Iterator:
    from app.main import app

    clients = []

    def _make(email: str = "ana@example.com", password: str = PASSWORD) -> Api:
        client = TestClient(app)
        clients.append(client)
        r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": email.split("@")[0]})
        assert r.status_code == 202, r.text
        r = client.post("/api/auth/verify-email", json={"token": last_link_token()})
        assert r.status_code == 200, r.text
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return Api(client)

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def anon():
    from app.main import app

    with TestClient(app) as c:
        yield c
