from __future__ import annotations

from app.config import Settings


def test_empty_env_vars_fall_back_to_defaults(monkeypatch):
    # O Compose repassa variáveis vazias do .env; não podem quebrar a inicialização.
    monkeypatch.setenv("CREDENTIALS_ACTIVE_KEY_VERSION", "")
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "")
    s = Settings()
    assert s.credentials_active_key_version is None
    assert s.smtp_user is None
    assert s.sync_interval_minutes == 15


def test_active_key_version_parsed_when_set(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_ACTIVE_KEY_VERSION", "2")
    assert Settings().credentials_active_key_version == 2
