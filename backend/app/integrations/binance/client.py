"""Cliente HTTP mínimo para a API oficial da Binance (somente endpoints de leitura).

- Assinatura HMAC-SHA256 das requisições privadas.
- Respeita os limites: lê ``X-MBX-USED-WEIGHT-1M`` / ``X-SAPI-USED-UID-WEIGHT-1M``
  e pausa antes de atingir o teto; trata 429 (Retry-After) e 418 (banimento).
- Timeout em todas as chamadas e retentativa curta para falhas transitórias.
- Nunca inclui chave, assinatura ou query assinada em mensagens de erro.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections.abc import Callable
from urllib.parse import urlencode

import httpx

from app.integrations.base import AdapterError, InvalidCredentials, RateLimited, TemporaryError

log = logging.getLogger("app.integrations.binance")

IP_WEIGHT_LIMIT = 6000
UID_WEIGHT_LIMIT = 180000
_SAFETY = 0.8
_AUTH_ERROR_CODES = {-2008, -2014, -2015, -1022, -1002}


class BinanceClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        *,
        base_url: str = "https://api.binance.com",
        timeout: float = 15.0,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
    ):
        self._key = api_key
        self._secret = api_secret.encode() if api_secret else None
        self._http = httpx.Client(base_url=base_url, timeout=timeout)
        self._sleep = sleep
        self._max_retries = max_retries
        self._time_offset_ms: int | None = None

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------ helpers
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _sync_time(self) -> None:
        data = self.public("/api/v3/time")
        self._time_offset_ms = int(data["serverTime"]) - self._now_ms()

    def _throttle(self, response: httpx.Response) -> None:
        for header, limit in (("x-mbx-used-weight-1m", IP_WEIGHT_LIMIT), ("x-sapi-used-uid-weight-1m", UID_WEIGHT_LIMIT)):
            used = response.headers.get(header)
            if used and used.isdigit() and int(used) >= limit * _SAFETY:
                wait = 60 - (time.time() % 60) + 1
                log.warning("binance_weight_throttle", extra={"header": header, "used": int(used), "wait": round(wait, 1)})
                self._sleep(wait)

    def _request(self, path: str, params: dict | None, signed: bool) -> object:
        attempt = 0
        resynced = False
        while True:
            attempt += 1
            query = dict(params or {})
            headers = {}
            if signed:
                if not self._key or not self._secret:
                    raise InvalidCredentials("Credenciais ausentes.")
                if self._time_offset_ms is None:
                    self._sync_time()
                query["timestamp"] = self._now_ms() + (self._time_offset_ms or 0)
                query["recvWindow"] = 10000
                qs = urlencode(query)
                sig = hmac.new(self._secret, qs.encode(), hashlib.sha256).hexdigest()
                url = f"{path}?{qs}&signature={sig}"
                headers["X-MBX-APIKEY"] = self._key
            else:
                url = f"{path}?{urlencode(query)}" if query else path
            try:
                resp = self._http.get(url, headers=headers)
            except httpx.TimeoutException:
                if attempt <= self._max_retries:
                    self._sleep(2**attempt)
                    continue
                raise TemporaryError(f"Tempo esgotado ao consultar a Binance ({path}).") from None
            except httpx.HTTPError:
                if attempt <= self._max_retries:
                    self._sleep(2**attempt)
                    continue
                raise TemporaryError(f"Falha de rede ao consultar a Binance ({path}).") from None

            self._throttle(resp)
            if resp.status_code == 200:
                return resp.json()

            code, msg = None, ""
            try:
                body = resp.json()
                code, msg = body.get("code"), str(body.get("msg", ""))[:200]
            except ValueError:
                pass

            if resp.status_code in (429, 418):
                retry_after = float(resp.headers.get("retry-after", "60") or 60)
                raise RateLimited(f"Limite de requisições da Binance atingido (HTTP {resp.status_code}).", retry_after)
            if code == -1021 and not resynced:
                resynced = True
                self._sync_time()
                continue
            if resp.status_code == 401 or code in _AUTH_ERROR_CODES:
                raise InvalidCredentials(f"Credencial rejeitada pela Binance (código {code}).")
            if resp.status_code >= 500:
                if attempt <= self._max_retries:
                    self._sleep(2**attempt)
                    continue
                raise TemporaryError(f"Binance indisponível (HTTP {resp.status_code}).")
            raise AdapterError(f"Erro da Binance em {path}: HTTP {resp.status_code} código {code} {msg}".strip())

    def public(self, path: str, params: dict | None = None) -> object:
        return self._request(path, params, signed=False)

    def signed(self, path: str, params: dict | None = None) -> object:
        return self._request(path, params, signed=True)
