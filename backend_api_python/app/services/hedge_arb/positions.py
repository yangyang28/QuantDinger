"""Read spot / perp leg sizes from Binance clients."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.symbols import _split_base_quote


def spot_base_balance(client: BinanceSpotClient, symbol: str) -> float:
    base, _ = _split_base_quote(symbol)
    if not base:
        return 0.0
    try:
        acct = client.get_account() or {}
    except Exception:
        return 0.0
    balances = acct.get("balances") if isinstance(acct, dict) else None
    if not isinstance(balances, list):
        return 0.0
    for row in balances:
        if not isinstance(row, dict):
            continue
        if str(row.get("asset") or "").upper() != base.upper():
            continue
        try:
            free = float(row.get("free") or 0.0)
            locked = float(row.get("locked") or 0.0)
            return max(0.0, free + locked)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def perp_short_size(client: BinanceFuturesClient, symbol: str) -> float:
    """Return absolute short size (base qty) for the symbol."""
    try:
        rows = client.get_positions(symbol=symbol) or []
    except Exception:
        return 0.0
    total = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            amt = float(row.get("positionAmt") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        pos_side = str(row.get("positionSide") or "").upper()
        if pos_side == "SHORT" and amt < 0:
            total += abs(amt)
        elif pos_side in ("", "BOTH") and amt < 0:
            total += abs(amt)
        elif pos_side == "SHORT" and amt > 0:
            total += amt
    return total


def read_live_legs(
    spot_client: BinanceSpotClient,
    perp_client: BinanceFuturesClient,
    symbol: str,
) -> Tuple[float, float]:
    return spot_base_balance(spot_client, symbol), perp_short_size(perp_client, symbol)
