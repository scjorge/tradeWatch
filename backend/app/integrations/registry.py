"""Registro de adaptadores de corretoras. Para adicionar uma corretora, implemente
``ExchangeAdapter`` e registre a classe aqui."""

from __future__ import annotations

from app.integrations.base import ExchangeAdapter, PriceSource, ProviderInfo
from app.integrations.binance.adapter import BinanceAdapter, BinancePriceSource

ADAPTERS: dict[str, type[ExchangeAdapter]] = {
    BinanceAdapter.info.key: BinanceAdapter,
}

# Fábricas substituíveis nos testes.
_adapter_factory = None
_price_source_factory = None


def provider_info(key: str) -> ProviderInfo:
    return ADAPTERS[key].info


def build_adapter(provider_key: str, credentials: dict, settings: dict | None = None) -> ExchangeAdapter:
    if _adapter_factory is not None:
        return _adapter_factory(provider_key, credentials, settings)
    cls = ADAPTERS.get(provider_key)
    if cls is None:
        raise KeyError(provider_key)
    return cls(credentials, settings)


def build_price_source() -> PriceSource:
    if _price_source_factory is not None:
        return _price_source_factory()
    return BinancePriceSource()


def set_factories(adapter_factory=None, price_source_factory=None) -> None:
    global _adapter_factory, _price_source_factory
    _adapter_factory = adapter_factory
    _price_source_factory = price_source_factory
