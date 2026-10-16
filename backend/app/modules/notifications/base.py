"""Contrato de canais de notificação, independente do Telegram."""

from __future__ import annotations

import abc
from dataclasses import dataclass


class ChannelError(Exception):
    """Falha ao usar o canal. A mensagem já vem sem segredos."""

    def __init__(self, message: str, *, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


@dataclass
class ChannelIdentity:
    display: str
    meta: dict


class NotificationChannelAdapter(abc.ABC):
    kind: str

    @abc.abstractmethod
    def check(self) -> ChannelIdentity:
        """Valida as credenciais do canal (ex.: token do bot)."""

    @abc.abstractmethod
    def send(self, destination: dict, text: str) -> None: ...


EVENT_TYPES: dict[str, str] = {
    "order_filled": "Compra ou venda detectada",
    "execution_new": "Nova execução identificada",
    "sync_completed": "Sincronização concluída",
    "integration_failure": "Falha de integração",
    "credential_invalid": "Credencial inválida",
    "daily_summary": "Resumo diário de resultados",
    "equity_change": "Variação de patrimônio",
}

# Padrões: evitar ruído — sincronização concluída desativada por padrão.
DEFAULT_ENABLED = {k: k != "sync_completed" for k in EVENT_TYPES}
DEFAULT_SETTINGS = {
    "daily_summary": {"hour": 20},
    "equity_change": {"threshold_pct": 5},
}
