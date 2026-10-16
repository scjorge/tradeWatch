"""Configuração da aplicação.

Segredos podem ser fornecidos diretamente por variável de ambiente ou, de forma
preferencial, por arquivo (Docker secrets): para qualquer campo marcado em
``_SECRET_FIELDS`` a variável ``<NOME>_FILE`` aponta para o arquivo com o valor.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SECRET_FIELDS = ("postgres_password", "smtp_password", "credentials_keys")


class Settings(BaseSettings):
    # env_ignore_empty: o Compose repassa variáveis vazias do .env (ex.: CREDENTIALS_ACTIVE_KEY_VERSION=);
    # elas devem valer como "não definidas" e usar o padrão.
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False, env_ignore_empty=True)

    app_env: str = "production"
    app_base_url: str = "http://localhost:8080"
    # Origens extras aceitas em requisições que alteram estado, separadas por vírgula.
    allowed_origins: str = ""
    log_level: str = "INFO"

    # Banco de dados: DATABASE_URL tem prioridade; caso contrário é montada a partir de POSTGRES_*.
    database_url: str | None = None
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "tradewatch"
    postgres_user: str = "tradewatch"
    postgres_password: str | None = None

    # Sessões e cookies
    cookie_secure: bool = True
    session_ttl_hours: int = 72
    session_idle_minutes: int = 60 * 12
    require_email_verification: bool = True

    # Proteção de login
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    rate_limit_auth_per_minute: int = 20

    # Cofre de credenciais. Formato: uma chave por linha "<versão>:<base64 de 32 bytes>".
    credentials_keys: str | None = None
    credentials_active_key_version: int | None = None

    # E-mail
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "TradeWatch <no-reply@tradewatch.local>"
    smtp_starttls: bool = True

    # Integrações externas
    binance_base_url: str = "https://api.binance.com"
    telegram_api_base: str = "https://api.telegram.org"
    http_timeout_seconds: float = 15.0

    # Worker
    sync_interval_minutes: int = 15
    worker_poll_seconds: float = 3.0
    job_max_attempts: int = 5
    job_stale_minutes: int = 15
    failure_alert_threshold: int = 3

    @model_validator(mode="before")
    @classmethod
    def _load_secret_files(cls, data: dict) -> dict:
        data = dict(data or {})
        for field in _SECRET_FIELDS:
            file_var = os.environ.get(f"{field.upper()}_FILE")
            if file_var and not data.get(field) and not os.environ.get(field.upper()):
                path = Path(file_var)
                if path.is_file():
                    data[field] = path.read_text().strip()
        return data

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
