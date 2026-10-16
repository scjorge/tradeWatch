"""Checagem do cabeçalho Origin em requisições que alteram estado (defesa extra contra CSRF)."""

from __future__ import annotations

from urllib.parse import urlsplit


def _netloc(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    return f"{host}:{port}" if host else ""


def _host_netloc(host_header: str, scheme: str) -> str:
    return _netloc(f"{scheme}://{host_header}") if host_header else ""


def origin_allowed(origin: str | None, host_header: str | None, scheme: str, app_base_url: str, extra_origins: str = "") -> bool:
    """Aceita requisições sem Origin, da mesma origem do pedido (Host), de APP_BASE_URL ou de ALLOWED_ORIGINS.

    A comparação é por host:porta. O esquema é ignorado porque, atrás de proxies
    (Traefik → nginx → API), o esquema visto pela API pode ser http mesmo com HTTPS na borda.
    """
    if not origin:
        return True
    if origin == "null":
        return False
    o = _netloc(origin)
    if not o:
        return False
    allowed = {_netloc(app_base_url)}
    allowed |= {_netloc(x) for x in extra_origins.split(",") if x.strip()}
    if host_header:
        # Host sem porta explícita: vale a porta padrão do esquema da origem.
        allowed.add(_host_netloc(host_header, urlsplit(origin).scheme or scheme))
    return o in allowed
