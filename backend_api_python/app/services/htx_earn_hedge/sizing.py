"""1:1 spot/perp sizing helpers for HTX earn hedge (fees inclusive)."""
from __future__ import annotations

from typing import Any, Dict


# HTX retail-ish defaults; overridden by trading_config when present.
DEFAULT_SPOT_TAKER_FEE = 0.002
DEFAULT_SWAP_TAKER_FEE = 0.0005


def plan_1to1_deploy(
    *,
    spot_usdt: float,
    perp_notional_usdt: float,
    price: float,
    spot_fee_rate: float = DEFAULT_SPOT_TAKER_FEE,
    perp_fee_rate: float = DEFAULT_SWAP_TAKER_FEE,
) -> Dict[str, Any]:
    """Plan a 1:1 base-qty deploy after estimating spot/perp taker fees.

    Target base qty = min(spot_net_base, perp_budget_base).
    Spot buy USDT may be slightly above target×price to leave room for fees.
    """
    spot_u = max(float(spot_usdt or 0.0), 0.0)
    perp_u = max(float(perp_notional_usdt or 0.0), 0.0)
    px = float(price or 0.0)
    sf = max(0.0, min(float(spot_fee_rate or 0.0), 0.05))
    pf = max(0.0, min(float(perp_fee_rate or 0.0), 0.05))

    if px <= 0 or (spot_u <= 0 and perp_u <= 0):
        return {
            "price": px,
            "target_base_qty": 0.0,
            "spot_buy_usdt": 0.0,
            "perp_short_qty": 0.0,
            "spot_fee_est_usdt": 0.0,
            "perp_fee_est_usdt": 0.0,
            "total_fee_est_usdt": 0.0,
            "aligned_notional_usdt": 0.0,
            "spot_capital_usdt": spot_u,
            "perp_capital_usdt": perp_u,
            "spot_fee_rate": sf,
            "perp_fee_rate": pf,
        }

    spot_base_net = (spot_u * (1.0 - sf)) / px if spot_u > 0 else 0.0
    perp_base_budget = perp_u / px if perp_u > 0 else 0.0
    if spot_base_net > 0 and perp_base_budget > 0:
        target_base = min(spot_base_net, perp_base_budget)
    else:
        target_base = max(spot_base_net, perp_base_budget)

    # Gross spot spend so that after fee we still hold ≈ target_base.
    spot_buy_usdt = (target_base * px) / (1.0 - sf) if sf < 1.0 else target_base * px
    # Never spend more than the user allocated for spot.
    spot_buy_usdt = min(spot_buy_usdt, spot_u) if spot_u > 0 else spot_buy_usdt
    perp_short_qty = min(target_base, perp_base_budget) if perp_base_budget > 0 else target_base

    spot_fee_est = spot_buy_usdt * sf
    perp_notional_used = perp_short_qty * px
    perp_fee_est = perp_notional_used * pf

    return {
        "price": px,
        "target_base_qty": round(target_base, 8),
        "spot_buy_usdt": round(spot_buy_usdt, 4),
        "perp_short_qty": round(perp_short_qty, 8),
        "spot_fee_est_usdt": round(spot_fee_est, 4),
        "perp_fee_est_usdt": round(perp_fee_est, 4),
        "total_fee_est_usdt": round(spot_fee_est + perp_fee_est, 4),
        "aligned_notional_usdt": round(target_base * px, 4),
        "spot_capital_usdt": spot_u,
        "perp_capital_usdt": perp_u,
        "spot_fee_rate": sf,
        "perp_fee_rate": pf,
    }


def alignment_metrics(
    *,
    spot_or_earn_qty: float,
    perp_qty: float,
    price: float = 0.0,
) -> Dict[str, Any]:
    """Report how close spot/earn vs perp short are to 1:1."""
    s = float(spot_or_earn_qty or 0.0)
    p = float(perp_qty or 0.0)
    gap = s - p
    denom = min(s, p) if min(s, p) > 0 else max(s, p)
    drift_pct = (abs(gap) / denom) if denom > 0 else 0.0
    matched = abs(gap) <= max(1e-8, denom * 0.01)  # within 1% or dust
    px = float(price or 0.0)
    return {
        "spot_base_qty": s,
        "perp_base_qty": p,
        "base_gap": gap,
        "qty_drift_pct": drift_pct,
        "qty_matched": matched,
        "spot_notional_usdt": s * px if px > 0 else 0.0,
        "perp_notional_usdt": p * px if px > 0 else 0.0,
    }
