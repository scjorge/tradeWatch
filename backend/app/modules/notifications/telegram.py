"""Canal Telegram (Bot API). O token nunca aparece em logs, erros ou respostas."""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.core.redaction import redact_text
from app.modules.notifications.base import ChannelError, ChannelIdentity, NotificationChannelAdapter


class TelegramChannel(NotificationChannelAdapter):
    kind = "telegram"

    def __init__(self, bot_token: str, http: httpx.Client | None = None):
        s = get_settings()
        self._token = bot_token
        self._base = s.telegram_api_base.rstrip("/")
        self._http = http or httpx.Client(timeout=s.http_timeout_seconds)

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, payload: dict | None = None) -> dict:
        url = f"{self._base}/bot{self._token}/{method}"
        try:
            resp = self._http.post(url, json=payload or {})
        except httpx.HTTPError as exc:
            # A exceção do httpx contém a URL (com o token); devolvemos apenas o tipo.
            raise ChannelError(f"Falha de rede ao contatar o Telegram ({type(exc).__name__}).") from None
        try:
            body = resp.json()
        except ValueError:
            raise ChannelError(f"Resposta inválida do Telegram (HTTP {resp.status_code}).") from None
        if not body.get("ok"):
            desc = redact_text(str(body.get("description", "erro desconhecido")), 200)
            permanent = resp.status_code in (401, 403, 404) or resp.status_code == 400
            raise ChannelError(f"Telegram recusou a requisição: {desc}", permanent=permanent)
        return body["result"]

    def check(self) -> ChannelIdentity:
        me = self._call("getMe")
        return ChannelIdentity(display=f"@{me.get('username')}", meta={"bot_username": me.get("username"), "bot_id": me.get("id")})

    def find_verification(self, matches) -> dict | None:
        """Procura, nas atualizações recentes do bot, uma mensagem com o código de verificação.

        O usuário envia o código ao bot (chat privado) ou no grupo onde o bot foi
        adicionado. Assim fica comprovado que ele controla o destino. ``matches``
        recebe cada palavra das mensagens e diz se é o código esperado (comparado por hash).
        """
        updates = self._call("getUpdates", {"limit": 100, "allowed_updates": ["message", "channel_post"]})
        for upd in reversed(updates):
            msg = upd.get("message") or upd.get("channel_post") or {}
            words = (msg.get("text") or "").replace("@", " ").split()
            if any(matches(w) for w in words):
                chat = msg.get("chat", {})
                return {
                    "chat_id": chat.get("id"),
                    "chat_type": chat.get("type"),
                    "chat_title": chat.get("title") or chat.get("username") or chat.get("first_name"),
                }
        return None

    def send(self, destination: dict, text: str) -> None:
        self._call(
            "sendMessage",
            {"chat_id": destination["chat_id"], "text": text[:4000], "disable_web_page_preview": True},
        )


_factory = None


def build_telegram(token: str) -> TelegramChannel:
    if _factory is not None:
        return _factory(token)
    return TelegramChannel(token)


def set_factory(factory) -> None:
    global _factory
    _factory = factory
