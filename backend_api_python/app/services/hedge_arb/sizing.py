"""Notional sizing and drift helpers for two-leg hedge."""
from __future__ import annotations


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
