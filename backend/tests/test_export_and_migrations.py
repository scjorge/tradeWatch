from __future__ import annotations

from alembic import command
from sqlalchemy import text


def test_csv_export_neutralizes_formulas():
    from app.modules.trades.router_data import _csv_safe

    assert _csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _csv_safe("-12.5") == "-12.5"


def test_import_endpoint_does_not_exist(make_user):
    api = make_user()
    r = api.post("/api/integrations/connections/00000000-0000-0000-0000-000000000000/import-csv", json={})
    assert r.status_code in (404, 405)


def test_migrations_downgrade_and_upgrade(alembic_cfg, db):
    db.close()
    command.downgrade(alembic_cfg, "base")
    from app.db import session_factory

    with session_factory()() as s:
        assert s.execute(text("select to_regclass('public.users')")).scalar() is None
    command.upgrade(alembic_cfg, "head")
    with session_factory()() as s:
        assert s.execute(text("select to_regclass('public.trade_cycles')")).scalar() is not None
