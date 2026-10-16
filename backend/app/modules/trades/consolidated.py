"""Compra e venda consolidada (função pura).

A tabela "Compra e venda" tem uma linha por pedaço (execução de compra × execução de
venda). Uma ordem executada em várias partes (fills) gera várias linhas. Aqui as
linhas da mesma ordem de compra com a mesma ordem de venda viram uma linha só:

  quantidades, totais, valores em BRL, taxas e lucro  → somados
  valor unitário e câmbio                              → média ponderada
  % lucro                                              → lucro somado ÷ compra BRL somada
  dias                                                 → média ponderada pela quantidade
  data da compra / venda                               → primeira compra / última venda

Qualquer parte sem valor (None) deixa o total correspondente sem valor, para não
apresentar uma soma parcial como se fosse completa.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from decimal import Decimal

ZERO = Decimal(0)

SUM_FIELDS = (
    "buy_quantity", "buy_total", "buy_total_brl",
    "sell_quantity", "sell_total", "sell_total_brl",
    "pnl_brl", "pnl_quote", "fx_effect_brl", "fees_brl",
)
# campo → campo usado como peso
WEIGHTED_FIELDS = {
    "buy_price": "buy_quantity",
    "buy_unit_brl": "buy_quantity",
    "buy_fx": "buy_total",
    "sell_price": "sell_quantity",
    "sell_unit_brl": "sell_quantity",
    "sell_fx": "sell_total",
}


def _sum(values: list[Decimal | None]) -> Decimal | None:
    if any(v is None for v in values):
        return None
    return sum(values, ZERO)


def _weighted(parts: list[dict], field: str, weight: str) -> Decimal | None:
    pairs = [(p.get(field), p.get(weight)) for p in parts]
    if any(v is None or w is None for v, w in pairs):
        return None
    total_w = sum((w for _, w in pairs), ZERO)
    if not total_w:
        # sem peso (ex.: quantidades zeradas): usa o valor se for igual em todas as partes
        values = {v for v, _ in pairs}
        return values.pop() if len(values) == 1 else None
    return sum((v * w for v, w in pairs), ZERO) / total_w


def _fee(parts: list[dict], qty_field: str, asset_field: str) -> tuple[Decimal | None, str | None]:
    """Soma a taxa se todas as partes cobradas usam o mesmo ativo; ativos diferentes não são somáveis."""
    charged = [p for p in parts if p.get(qty_field)]
    if not charged:
        return (ZERO if any(p.get(qty_field) is not None for p in parts) else None), parts[0].get(asset_field)
    assets = {p.get(asset_field) for p in charged}
    if len(assets) > 1:
        return None, None
    return sum((p[qty_field] for p in charged), ZERO), assets.pop()


def _joined(parts: list[dict], field: str, sep: str = ", ") -> str | None:
    seen: list[str] = []
    for p in parts:
        v = p.get(field)
        if v and v not in seen:
            seen.append(v)
    return sep.join(seen) or None


def merge(parts: list[dict]) -> dict:
    """Junta as partes de um grupo. Valores numéricos devem chegar como ``Decimal`` (ou None)."""
    first = parts[0]
    out = dict(first)
    for f in SUM_FIELDS:
        out[f] = _sum([p.get(f) for p in parts])
    for f, w in WEIGHTED_FIELDS.items():
        out[f] = _weighted(parts, f, w)
    out["buy_fee"], out["buy_fee_asset"] = _fee(parts, "buy_fee", "buy_fee_asset")
    out["sell_fee"], out["sell_fee_asset"] = _fee(parts, "sell_fee", "sell_fee_asset")

    buy_brl, pnl = out["buy_total_brl"], out["pnl_brl"]
    out["pnl_pct"] = pnl / buy_brl * 100 if pnl is not None and buy_brl else None

    weight = "sell_quantity" if all(p.get("sell_quantity") for p in parts) else "buy_quantity"
    out["holding_days"] = _weighted(parts, "holding_days", weight)

    buys = [p["buy_at"] for p in parts if p.get("buy_at")]
    sells = [p["sell_at"] for p in parts if p.get("sell_at")]
    out["buy_at"] = min(buys) if buys else None
    out["sell_at"] = max(sells) if sells else None
    refs = [p["ref_at"] for p in parts if p.get("ref_at")]
    out["ref_at"] = max(refs) if refs else None

    out["complete"] = all(p.get("complete") for p in parts)
    out["note"] = _joined(parts, "note", " ")
    out["account"] = _joined(parts, "account")
    out["quote"] = _joined(parts, "quote")
    out["sell_quote"] = _joined(parts, "sell_quote")
    out["estimated"] = any(p.get("estimated") for p in parts)
    out["price_source"] = next((p["price_source"] for p in parts if p.get("price_source")), None)

    out["parts"] = len(parts)
    out["buy_executions"] = len({p["buy_execution_id"] for p in parts if p.get("buy_execution_id")})
    out["sell_executions"] = len({p["sell_execution_id"] for p in parts if p.get("sell_execution_id")})
    return out


def consolidate(rows: Iterable[tuple[Hashable, dict]]) -> list[dict]:
    """Agrupa ``(chave, linha)`` mantendo a ordem da primeira ocorrência de cada chave."""
    groups: dict[Hashable, list[dict]] = {}
    for key, row in rows:
        groups.setdefault(key, []).append(row)
    return [merge(parts) for parts in groups.values()]
