"""Public-market signals for funding-rate / basis hedge decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from app.services.live_trading.base import _get_requests_verify
from app.services.live_trading.symbols import to_binance_futures_symbol


@dataclass
class HedgeArbSignals:
    symbol: str
    funding_rate: float
    spot_price: float
    perp_mark_price: float
    basis_pct: float
    source: str = "binance_public"


def _public_get(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    resp = requests.get(url, params=params or {}, timeout=10, verify=_get_requests_verify())
    resp.raise_for_status()
    return resp.json()


def fetch_funding_rate(symbol: str, *, testnet: bool = False) -> float:
    pair = to_binance_futures_symbol(symbol)
    base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
    data = _public_get(f"{base}/fapi/v1/premiumIndex", params={"symbol": pair})
    if isinstance(data, dict):
        try:
            return float(data.get("lastFundingRate") or 0.0)
        except (TypeError, ValueError):
            pass
    data = _public_get(f"{base}/fapi/v1/fundingRate", params={"symbol": pair, "limit": 1})
    if isinstance(data, list) and data:
        try:
            return float(data[-1].get("fundingRate") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def fetch_spot_price(symbol: str, *, testnet: bool = False) -> float:
    pair = to_binance_futures_symbol(symbol)
    base = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
    data = _public_get(f"{base}/api/v3/ticker/price", params={"symbol": pair})
    if isinstance(data, dict):
        try:
            return float(data.get("price") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def fetch_perp_mark_price(symbol: str, *, testnet: bool = False) -> float:
    pair = to_binance_futures_symbol(symbol)
    base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
    data = _public_get(f"{base}/fapi/v1/premiumIndex", params={"symbol": pair})
    if isinstance(data, dict):
        try:
            return float(data.get("markPrice") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def compute_basis_pct(spot_price: float, perp_price: float) -> float:
    if spot_price <= 0:
        return 0.0
    return (float(perp_price) - float(spot_price)) / float(spot_price)


def collect_signals(symbol: str, *, testnet: bool = False) -> HedgeArbSignals:
    funding = fetch_funding_rate(symbol, testnet=testnet)
    spot = fetch_spot_price(symbol, testnet=testnet)
    perp = fetch_perp_mark_price(symbol, testnet=testnet)
    basis = compute_basis_pct(spot, perp)
    return HedgeArbSignals(
        symbol=symbol,
        funding_rate=funding,
        spot_price=spot,
        perp_mark_price=perp,
        basis_pct=basis,
    )


def fetch_historical_funding(
    symbol: str,
    *,
    limit: int = 500,
    testnet: bool = False,
) -> list[dict]:
    """Fetch Binance funding rate history (8h intervals)."""
    pair = to_binance_futures_symbol(symbol)
    base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
    lim = max(1, min(1000, int(limit or 500)))
    data = _public_get(f"{base}/fapi/v1/fundingRate", params={"symbol": pair, "limit": lim})
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            out.append({
                "funding_time_ms": int(row.get("fundingTime") or 0),
                "funding_rate": float(row.get("fundingRate") or 0.0),
            })
        except (TypeError, ValueError):
            continue
    return out


def should_enter(signals: HedgeArbSignals, *, entry_funding_rate: float, max_basis_pct: float) -> bool:
    if signals.funding_rate < entry_funding_rate:
        return False
    if max_basis_pct > 0 and abs(signals.basis_pct) > max_basis_pct:
        return False
    return signals.spot_price > 0 and signals.perp_mark_price > 0


def should_exit(
    signals: HedgeArbSignals,
    *,
    exit_funding_rate: float,
    max_basis_pct: float,
    hold_hours: float = 0.0,
    max_hold_hours: float = 0.0,
) -> bool:
    if signals.funding_rate < exit_funding_rate:
        return True
    if max_basis_pct > 0 and abs(signals.basis_pct) > max_basis_pct * 2:
        return True
    if max_hold_hours > 0 and hold_hours >= max_hold_hours:
        return True
    return False
