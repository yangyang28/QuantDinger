"""Notional sizing and drift helpers for two-leg hedge."""
from __future__ import annotations

from typing import Any, Tuple

from app.services.live_trading.base import LiveTradingError
from app.services.live_trading.binance_spot import BinanceSpotClient


def target_base_qty(notional_usdt: float, reference_price: float) -> float:
    if reference_price <= 0 or notional_usdt <= 0:
        return 0.0
    return float(notional_usdt) / float(reference_price)


def leg_notional_usdt(qty: float, price: float) -> float:
    if qty <= 0 or price <= 0:
        return 0.0
    return float(qty) * float(price)


def notional_drift_pct(
    spot_qty: float,
    spot_price: float,
    perp_qty: float,
    perp_price: float,
) -> float:
    spot_n = leg_notional_usdt(spot_qty, spot_price)
    perp_n = leg_notional_usdt(perp_qty, perp_price)
    if spot_n <= 0 and perp_n <= 0:
        return 0.0
    avg = (spot_n + perp_n) / 2.0
    if avg <= 0:
        return 0.0
    return abs(spot_n - perp_n) / avg


def rebalance_delta_base(
    spot_qty: float,
    perp_qty: float,
    spot_price: float,
    perp_price: float,
) -> float:
    """Positive => need more perp short (or less spot long)."""
    spot_n = leg_notional_usdt(spot_qty, spot_price)
    perp_n = leg_notional_usdt(perp_qty, perp_price)
    ref_price = perp_price if perp_price > 0 else spot_price
    if ref_price <= 0:
        return 0.0
    return (spot_n - perp_n) / ref_price


def _min_market_base_qty(client: Any, *, symbol: str) -> float:
    try:
        fdict = client.get_symbol_filters(symbol=symbol) or {}
    except Exception:
        fdict = {}
    filt = BinanceSpotClient._pick_lot_filter(fdict, for_market=True)
    try:
        min_qty = float((filt or {}).get("minQty") or 0.0)
    except (TypeError, ValueError):
        min_qty = 0.0
    try:
        step = float((filt or {}).get("stepSize") or 0.0)
    except (TypeError, ValueError):
        step = 0.0
    return max(min_qty, step, 0.0)


def normalize_market_base_qty(client: Any, *, symbol: str, quantity: float) -> float:
    q_dec, _ = client._normalize_quantity(symbol=symbol, quantity=float(quantity), for_market=True)
    return float(q_dec or 0.0)


def min_entry_notional_usdt(
    *,
    symbol: str,
    reference_price: float,
    perp_client: Any,
    spot_client: Any,
) -> float:
    """Rough minimum USDT notional so both legs satisfy market lot filters."""
    if reference_price <= 0:
        return 0.0
    perp_min = _min_market_base_qty(perp_client, symbol=symbol)
    spot_min = _min_market_base_qty(spot_client, symbol=symbol)
    base_min = max(perp_min, spot_min)
    if base_min <= 0:
        return 0.0
    return base_min * reference_price * 1.01


def plan_entry_base_qty(
    *,
    symbol: str,
    notional_usdt: float,
    reference_price: float,
    perp_client: Any,
    spot_client: Any,
) -> Tuple[float, float]:
    """
    Plan aligned base quantity for spot long + perp short entry.

    Returns (base_qty, estimated_quote_usdt).
    """
    if reference_price <= 0 or notional_usdt <= 0:
        raise LiveTradingError("invalid notional or reference price")

    raw_qty = float(notional_usdt) / float(reference_price)
    perp_qty = normalize_market_base_qty(perp_client, symbol=symbol, quantity=raw_qty)
    if perp_qty <= 0:
        need = min_entry_notional_usdt(
            symbol=symbol,
            reference_price=reference_price,
            perp_client=perp_client,
            spot_client=spot_client,
        )
        min_base = _min_market_base_qty(perp_client, symbol=symbol)
        raise LiveTradingError(
            f"notional {notional_usdt:.2f} USDT too small for {symbol} "
            f"(perp min qty≈{min_base:g}, need≈{need:.2f} USDT at price {reference_price:.2f})"
        )

    spot_qty = normalize_market_base_qty(spot_client, symbol=symbol, quantity=perp_qty)
    if spot_qty <= 0:
        need = min_entry_notional_usdt(
            symbol=symbol,
            reference_price=reference_price,
            perp_client=perp_client,
            spot_client=spot_client,
        )
        raise LiveTradingError(
            f"notional {notional_usdt:.2f} USDT too small for spot leg on {symbol} "
            f"(need≈{need:.2f} USDT)"
        )

    base_qty = min(perp_qty, spot_qty)
    quote_est = base_qty * reference_price
    return base_qty, quote_est


def spot_free_usdt(spot_client: Any) -> float:
    try:
        acct = spot_client.get_account() or {}
    except Exception:
        return 0.0
    for row in acct.get("balances") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("asset") or "").upper() == "USDT":
            try:
                return float(row.get("free") or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def validate_spot_buy_balance(
    *,
    spot_client: Any,
    quote_required: float,
    buffer_pct: float = 0.02,
) -> None:
    free = spot_free_usdt(spot_client)
    need = float(quote_required) * (1.0 + max(0.0, buffer_pct))
    if free + 1e-9 < need:
        raise LiveTradingError(
            f"insufficient spot USDT balance: free={free:.2f}, need≈{need:.2f} for hedge entry"
        )
