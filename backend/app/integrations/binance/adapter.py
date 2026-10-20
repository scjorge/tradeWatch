"""Adaptador Binance (Spot) — somente leitura."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.config import get_settings
from app.integrations.base import (
    BalanceDTO,
    Capabilities,
    CredentialField,
    ExchangeAdapter,
    ExecutionDTO,
    InsufficientPermissions,
    MovementDTO,
    OrderDTO,
    Page,
    PriceSource,
    ProviderInfo,
    SymbolInfo,
    ValidationResult,
)
from app.integrations.binance.client import BinanceClient

log = logging.getLogger("app.integrations.binance")

PAGE_LIMIT = 1000
MOVEMENT_WINDOW = timedelta(days=89)
DEFAULT_HISTORY_START = "2017-07-14"
DEFAULT_QUOTES = ("USDT", "BRL", "FDUSD", "USDC", "BTC", "ETH", "BNB")
FINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"}

# Permissões que tornam a chave inaceitável (o sistema é somente leitura).
FORBIDDEN_PERMISSIONS = {
    "enableWithdrawals": "saque",
    "enableInternalTransfer": "transferência interna",
    "permitsUniversalTransfer": "transferência universal",
    "enableSpotAndMarginTrading": "negociação spot/margem",
    "enableMargin": "margem",
    "enableFutures": "futuros",
    "enableVanillaOptions": "opções",
}

_exchange_info_cache: dict[str, tuple[float, dict[str, SymbolInfo]]] = {}
_cache_lock = threading.Lock()


def _ms_to_dt(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, UTC)


def _dt_to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _parse_binance_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def _d(value) -> Decimal:
    return Decimal(str(value)) if value is not None and value != "" else Decimal(0)


def _client(api_key: str | None = None, api_secret: str | None = None) -> BinanceClient:
    s = get_settings()
    return BinanceClient(api_key, api_secret, base_url=s.binance_base_url, timeout=s.http_timeout_seconds)


def load_exchange_info(client: BinanceClient) -> dict[str, SymbolInfo]:
    base = str(client._http.base_url)
    with _cache_lock:
        cached = _exchange_info_cache.get(base)
        if cached and time.time() - cached[0] < 3600:
            return cached[1]
    data = client.public("/api/v3/exchangeInfo")
    symbols = {
        s["symbol"]: SymbolInfo(s["symbol"], s["baseAsset"], s["quoteAsset"])
        for s in data.get("symbols", [])  # type: ignore[union-attr]
    }
    with _cache_lock:
        _exchange_info_cache[base] = (time.time(), symbols)
    return symbols


class BinanceAdapter(ExchangeAdapter):
    info = ProviderInfo(
        key="binance",
        name="Binance",
        docs_url="https://www.binance.com/pt-BR/support/faq/360002502072",
        credential_fields=(
            CredentialField("api_key", "API Key", secret=False, help="Chave pública gerada na Binance."),
            CredentialField("api_secret", "Secret Key", secret=True, help="Exibida pela Binance apenas uma vez."),
        ),
        instructions=(
            "Acesse binance.com, entre na sua conta e abra o menu do perfil > Gerenciamento de API (API Management).",
            "Clique em 'Criar API', escolha 'Gerada pelo sistema' (HMAC) e dê um nome, por exemplo 'TradeWatch'.",
            "Conclua a verificação de segurança (2FA, e-mail/SMS) solicitada pela Binance.",
            "Na tela de restrições, deixe marcado SOMENTE 'Ativar leitura' (Enable Reading). "
            "Não habilite negociação spot/margem, futuros, saques nem transferências — o TradeWatch recusa chaves com essas permissões.",
            "Recomendado: em 'Restrição de acesso por IP', escolha 'Restringir acesso apenas a IPs confiáveis' e informe o IP público do servidor do TradeWatch.",
            "Copie a API Key e a Secret Key e cole nos campos abaixo. A Secret Key só é exibida uma vez pela Binance; "
            "depois de salva aqui, ela é cifrada e nunca mais será exibida.",
        ),
        capabilities=Capabilities(
            balances=True,
            orders=True,
            executions=True,
            deposits=True,
            withdrawals=True,
            streams=False,
            read_only_enforced=True,
            rate_limit="6.000 de peso/min por IP; histórico de saques limitado por UID.",
            notes=(
                "Somente mercado Spot nesta versão.",
                "Execuções são buscadas por par. Pares de ativos já zerados devem ser informados em 'Pares adicionais'.",
                "Conversões (Convert), Earn e dust não são sincronizados nesta versão; vendas desses saldos aparecem como incompletas.",
            ),
        ),
    )

    def __init__(self, credentials: dict, settings: dict | None = None, client: BinanceClient | None = None):
        super().__init__(credentials, settings)
        self.client = client or _client(credentials.get("api_key"), credentials.get("api_secret"))

    def close(self) -> None:
        self.client.close()

    # ---------------------------------------------------------------- validação
    def validate_credentials(self) -> ValidationResult:
        restrictions = self.client.signed("/sapi/v1/account/apiRestrictions")
        assert isinstance(restrictions, dict)
        if not restrictions.get("enableReading"):
            raise InsufficientPermissions("A chave não possui a permissão de leitura habilitada.")
        enabled_forbidden = [label for k, label in FORBIDDEN_PERMISSIONS.items() if restrictions.get(k)]
        if enabled_forbidden:
            raise InsufficientPermissions(
                "Por segurança, use uma chave somente leitura. Desabilite na Binance: " + ", ".join(enabled_forbidden) + "."
            )
        # Confirma acesso efetivo à conta spot.
        self.client.signed("/api/v3/account", {"omitZeroBalances": "true"})
        warnings = []
        if not restrictions.get("ipRestrict"):
            warnings.append("Recomendamos restringir a chave a IPs confiáveis nas configurações da Binance.")
        return ValidationResult(
            ok=True,
            status="active",
            message="Conexão validada em modo somente leitura.",
            warnings=warnings,
            permissions={"reading": True, "ip_restricted": bool(restrictions.get("ipRestrict"))},
        )

    # ---------------------------------------------------------------- saldos
    def fetch_balances(self) -> list[BalanceDTO]:
        data = self.client.signed("/api/v3/account", {"omitZeroBalances": "true"})
        assert isinstance(data, dict)
        out = []
        for b in data.get("balances", []):
            free, locked = _d(b["free"]), _d(b["locked"])
            if free or locked:
                out.append(BalanceDTO(b["asset"], free, locked))
        return out

    # ---------------------------------------------------------------- pares
    def discover_symbols(self, assets: set[str], extra_symbols: list[str]) -> list[SymbolInfo]:
        info = load_exchange_info(self.client)
        quotes = tuple(self.settings.get("quote_assets") or DEFAULT_QUOTES)
        chosen: dict[str, SymbolInfo] = {}
        for asset in assets:
            for q in quotes:
                sym = info.get(f"{asset}{q}")
                if sym:
                    chosen[sym.symbol] = sym
        for raw in extra_symbols:
            sym = info.get(raw.strip().upper())
            if sym:
                chosen[sym.symbol] = sym
        return sorted(chosen.values(), key=lambda s: s.symbol)

    # ---------------------------------------------------------------- execuções
    def fetch_executions(self, symbol: SymbolInfo, cursor: dict) -> Page[ExecutionDTO]:
        from_id = int(cursor.get("from_id", 0))
        rows = self.client.signed(
            "/api/v3/myTrades", {"symbol": symbol.symbol, "fromId": from_id, "limit": PAGE_LIMIT}
        )
        assert isinstance(rows, list)
        items = [
            ExecutionDTO(
                external_id=str(r["id"]),
                external_order_id=str(r["orderId"]),
                symbol=symbol,
                side="BUY" if r["isBuyer"] else "SELL",
                quantity=_d(r["qty"]),
                price=_d(r["price"]),
                quote_quantity=_d(r["quoteQty"]),
                fee=_d(r["commission"]),
                fee_asset=r.get("commissionAsset"),
                is_maker=r.get("isMaker"),
                executed_at=_ms_to_dt(r["time"]),
            )
            for r in rows
        ]
        next_from = (max(int(r["id"]) for r in rows) + 1) if rows else from_id
        return Page(items, {"from_id": next_from}, has_more=len(rows) >= PAGE_LIMIT)

    # ---------------------------------------------------------------- ordens
    def fetch_orders(self, symbol: SymbolInfo, cursor: dict) -> Page[OrderDTO]:
        from_id = int(cursor.get("order_id", 0))
        rows = self.client.signed(
            "/api/v3/allOrders", {"symbol": symbol.symbol, "orderId": from_id, "limit": PAGE_LIMIT}
        )
        assert isinstance(rows, list)
        items = []
        for r in rows:
            price = _d(r.get("price"))
            items.append(
                OrderDTO(
                    external_id=str(r["orderId"]),
                    symbol=symbol,
                    side=r["side"],
                    order_type=r["type"],
                    status=r["status"],
                    price=price if price else None,
                    orig_qty=_d(r["origQty"]),
                    executed_qty=_d(r["executedQty"]),
                    cumulative_quote_qty=_d(r["cummulativeQuoteQty"]),
                    placed_at=_ms_to_dt(r["time"]),
                    updated_at=_ms_to_dt(r["updateTime"]) if r.get("updateTime") else None,
                    is_final=r["status"] in FINAL_ORDER_STATUSES,
                )
            )
        if rows:
            # Ordens ainda abertas são revisitadas na próxima sincronização para atualizar o estado.
            open_ids = [int(r["orderId"]) for r in rows if r["status"] not in FINAL_ORDER_STATUSES]
            last = max(int(r["orderId"]) for r in rows)
            has_more = len(rows) >= PAGE_LIMIT
            next_id = last + 1 if has_more or not open_ids else min(open_ids)
        else:
            next_id, has_more = from_id, False
        return Page(items, {"order_id": next_id}, has_more=has_more)

    # ---------------------------------------------------------------- depósitos/saques
    def fetch_movements(self, kind: str, cursor: dict) -> Page[MovementDTO]:
        start_ms = cursor.get("start_ms")
        if start_ms is None:
            hs = self.settings.get("history_start") or DEFAULT_HISTORY_START
            start_ms = _dt_to_ms(datetime.fromisoformat(hs).replace(tzinfo=UTC))
        now_ms = _dt_to_ms(datetime.now(UTC))
        end_ms = min(int(start_ms) + int(MOVEMENT_WINDOW.total_seconds() * 1000), now_ms)
        params = {"startTime": int(start_ms), "endTime": end_ms, "limit": PAGE_LIMIT}

        if kind == "deposit":
            rows = self.client.signed("/sapi/v1/capital/deposit/hisrec", params)
            assert isinstance(rows, list)
            items = [
                MovementDTO(
                    kind="deposit",
                    external_id=str(r.get("id") or r.get("txId")),
                    asset=r["coin"],
                    amount=_d(r["amount"]),
                    fee=Decimal(0),
                    network=r.get("network"),
                    tx_id=r.get("txId"),
                    status="completed" if r.get("status") == 1 else ("pending" if r.get("status") in (0, 6, 8) else "failed"),
                    occurred_at=_ms_to_dt(r["insertTime"]),
                )
                for r in rows
            ]
        elif kind == "withdrawal":
            rows = self.client.signed("/sapi/v1/capital/withdraw/history", params)
            assert isinstance(rows, list)
            items = [
                MovementDTO(
                    kind="withdrawal",
                    external_id=str(r["id"]),
                    asset=r["coin"],
                    amount=_d(r["amount"]),
                    fee=_d(r.get("transactionFee")),
                    network=r.get("network"),
                    tx_id=r.get("txId"),
                    status="completed" if r.get("status") == 6 else ("failed" if r.get("status") in (1, 3, 5) else "pending"),
                    occurred_at=_parse_binance_time(r.get("applyTime")) or _ms_to_dt(end_ms),
                )
                for r in rows
            ]
            # O histórico de saques tem limite de UID baixo; espaça as chamadas.
            self.client._sleep(float(self.settings.get("withdraw_pacing_seconds", 6.5)))
        else:
            raise ValueError(kind)

        if len(rows) >= PAGE_LIMIT:
            # Janela cheia: avança apenas até o último item retornado.
            last = max(_dt_to_ms(m.occurred_at) for m in items)
            return Page(items, {"start_ms": last}, has_more=True)
        # Mantém uma pequena sobreposição para capturar itens que mudam de estado (idempotência no banco).
        reached_now = end_ms >= now_ms
        next_start = end_ms - int(timedelta(days=7).total_seconds() * 1000) if reached_now else end_ms + 1
        return Page(items, {"start_ms": max(int(start_ms), next_start) if reached_now else next_start}, has_more=not reached_now)


class BinancePriceSource(PriceSource):
    name = "binance"

    def __init__(self, client: BinanceClient | None = None):
        s = get_settings()
        # Cotação é consulta leve e repetida: falha rápido em vez de segurar o botão por ~20 s.
        self.client = client or BinanceClient(base_url=s.binance_base_url, timeout=min(s.http_timeout_seconds, 8.0), max_retries=1)

    def close(self) -> None:
        self.client.close()

    def current_prices(self, wanted: set[str] | None = None) -> dict[tuple[str, str], Decimal]:
        rows = self.client.public("/api/v3/ticker/price")
        out: dict[tuple[str, str], Decimal] = {}
        if wanted:
            # Casa os símbolos pelos ativos pedidos; evita baixar o exchangeInfo (vários MB).
            names = {f"{a}{q}": (a, q) for a in wanted for q in wanted if a != q}
            for r in rows:  # type: ignore[union-attr]
                pair = names.get(r["symbol"])
                if pair:
                    out[pair] = _d(r["price"])
            return out
        info = load_exchange_info(self.client)
        for r in rows:  # type: ignore[union-attr]
            sym = info.get(r["symbol"])
            if sym:
                out[(sym.base_asset, sym.quote_asset)] = _d(r["price"])
        return out

    def historical_price(self, base: str, quote: str, at: datetime) -> Decimal | None:
        info = load_exchange_info(self.client)
        start = _dt_to_ms(at.replace(second=0, microsecond=0))
        for sym, invert in ((f"{base}{quote}", False), (f"{quote}{base}", True)):
            if sym not in info:
                continue
            rows = self.client.public("/api/v3/klines", {"symbol": sym, "interval": "1m", "startTime": start, "limit": 1})
            if rows:
                close = _d(rows[0][4])  # type: ignore[index]
                if close:
                    return (Decimal(1) / close) if invert else close
        return None
