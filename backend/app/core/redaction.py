"""Remoção de conteúdo sensível de textos que podem ir para logs, banco ou respostas."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Token de bot do Telegram (aparece inclusive dentro de URLs: /bot<token>/método)
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}"), "bot[REDACTED]"),
    (re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{30,}\b"), "[REDACTED]"),
    # Assinaturas e chaves em query strings
    (re.compile(r"(signature|apikey|api_key|token|secret|password)=([^&\s\"']+)", re.I), r"\1=[REDACTED]"),
    # Cabeçalhos de autenticação
    (re.compile(r"(X-MBX-APIKEY|Authorization|Cookie)[\"']?\s*[:=]\s*[\"']?[^\s,\"'}]+", re.I), r"\1: [REDACTED]"),
    # Strings longas com cara de chave (64 caracteres alfanuméricos, formato das chaves Binance)
    (re.compile(r"\b[A-Za-z0-9]{64}\b"), "[REDACTED]"),
]

SENSITIVE_KEYS = {
    "password",
    "new_password",
    "current_password",
    "api_key",
    "api_secret",
    "secret",
    "token",
    "bot_token",
    "credentials",
    "authorization",
    "cookie",
    "signature",
}


def redact_text(value: str | None, max_len: int = 1000) -> str | None:
    if value is None:
        return None
    text = str(value)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text[:max_len]


def redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else redact_obj(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_obj(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
