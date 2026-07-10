"""Quantity sizing and drift helpers for two-leg hedge (multi-exchange)."""
from __future__ import annotations

from typing import Any, Tuple

from app.services.hedge_arb.exchange_adapter import HedgeExchangeContext
from app.services.live_trading.base import LiveTradingError
from app.services.live_trading.spot_sizing import normalize_spot_base_quantity


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
    spot_n = leg_notional_usdt(spot_qty, spot_price)
    perp_n = leg_notional_usdt(perp_qty, perp_price)
    ref_price = perp_price if perp_price > 0 else spot_price
    if ref_price <= 0:
        return 0.0
    return (spot_n - perp_n) / ref_price


def base_qty_gap(spot_qty: float, perp_qty: float) -> float:
    return float(spot_qty) - float(perp_qty)


def qty_drift_metrics(spot_qty: float, perp_qty: float) -> tuple[float, float, bool]:
    gap = base_qty_gap(spot_qty, perp_qty)
    min_leg = min(float(spot_qty), float(perp_qty)) or max(float(spot_qty), float(perp_qty))
    drift_pct = (abs(gap) / min_leg) if min_leg > 0 else 0.0
    matched = abs(gap) <= 1e-8
    return gap, drift_pct, matched


def _normalize_perp_qty(client: Any, *, symbol: str, quantity: float) -> float:
    q = float(quantity or 0.0)
    if q <= 0:
        return 0.0
    if hasattr(client, "_normalize_quantity"):
        q_dec, _ = client._normalize_quantity(symbol=symbol, quantity=q, for_market=True)
        return float(q_dec or 0.0)
    if hasattr(client, "_normalize_order_size"):
        q_dec, _ = client._normalize_order_size(inst_id=symbol, market_type="swap", size=q)
        return float(q_dec or 0.0)
    if hasattr(client, "_normalize_size"):
        q_dec, _ = client._normalize_size(symbol=symbol, size=q, for_market=True)
        return float(q_dec or 0.0)
    if hasattr(client, "_normalize_qty"):
        q_dec, _ = client._normalize_qty(symbol=symbol, qty=q, for_market=True)
        return float(q_dec or 0.0)
    if hasattr(client, "_normalize_base_size"):
        q_dec, _ = client._normalize_base_size(symbol=symbol, size=q)
        return float(q_dec or 0.0)
    return q


def normalize_spot_qty(ctx: HedgeExchangeContext, quantity: float) -> float:
    try:
        return normalize_spot_base_quantity(
            ctx.spot_client,
            symbol=ctx.spot_symbol,
            quantity=float(quantity),
            for_market=True,
        )
    except Exception:
        if hasattr(ctx.spot_client, "_normalize_quantity"):
            q_dec, _ = ctx.spot_client._normalize_quantity(
                symbol=ctx.spot_symbol, quantity=float(quantity), for_market=True,
            )
            return float(q_dec or 0.0)
        return float(quantity or 0.0)


def normalize_perp_qty(ctx: HedgeExchangeContext, quantity: float) -> float:
    return _normalize_perp_qty(ctx.perp_client, symbol=ctx.perp_symbol, quantity=quantity)


def plan_entry_quantities(
    ctx: HedgeExchangeContext,
    *,
    spot_qty: float,
    perp_qty: float,
    reference_price: float,
) -> Tuple[float, float, float, float]:
    """
    Normalize user-defined spot/perp base quantities.

    Returns (spot_order_qty, perp_order_qty, spot_quote_est, perp_quote_est).
    """
    ref = float(reference_price or 0.0)
    raw_spot = float(spot_qty or 0.0)
    raw_perp = float(perp_qty or 0.0)
    if raw_spot <= 0 and raw_perp <= 0:
        raise LiveTradingError("spot_qty and perp_qty must be positive (or set notional_usdt)")

    spot_order = normalize_spot_qty(ctx, raw_spot) if raw_spot > 0 else 0.0
    perp_order = normalize_perp_qty(ctx, raw_perp) if raw_perp > 0 else 0.0

    if raw_spot > 0 and spot_order <= 0:
        raise LiveTradingError(
            f"spot_qty {raw_spot:g} below exchange min/step for {ctx.spot_symbol}"
        )
    if raw_perp > 0 and perp_order <= 0:
        raise LiveTradingError(
            f"perp_qty {raw_perp:g} below exchange min/step for {ctx.perp_symbol}"
        )

    spot_quote = spot_order * ref if ref > 0 else 0.0
    perp_quote = perp_order * ref if ref > 0 else 0.0
    return spot_order, perp_order, spot_quote, perp_quote


def plan_entry_base_qty(
    *,
    symbol: str,
    notional_usdt: float,
    reference_price: float,
    perp_client: Any,
    spot_client: Any,
) -> Tuple[float, float]:
    """Legacy notional-based planner (kept for tests/backward compat)."""
    if reference_price <= 0 or notional_usdt <= 0:
        raise LiveTradingError("invalid notional or reference price")
    raw_qty = float(notional_usdt) / float(reference_price)

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.spot_client = spot_client
    ctx.perp_client = perp_client
    ctx.spot_symbol = symbol
    ctx.perp_symbol = symbol

    spot_q = normalize_spot_qty(ctx, raw_qty)  # type: ignore[arg-type]
    perp_q = normalize_perp_qty(ctx, raw_qty)  # type: ignore[arg-type]
    base_qty = min(spot_q, perp_q) if spot_q > 0 and perp_q > 0 else 0.0
    if base_qty <= 0:
        raise LiveTradingError(
            f"notional {notional_usdt:.2f} USDT too small for {symbol} at price {reference_price:.2f}"
        )
    return base_qty, base_qty * reference_price


def align_dual_leg_qty(
    *,
    symbol: str,
    quantity: float,
    spot_client: Any,
    perp_client: Any,
) -> float:
    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.spot_client = spot_client
    ctx.perp_client = perp_client
    ctx.spot_symbol = symbol
    ctx.perp_symbol = symbol
    spot_q = normalize_spot_qty(ctx, quantity)  # type: ignore[arg-type]
    perp_q = normalize_perp_qty(ctx, quantity)  # type: ignore[arg-type]
    if spot_q <= 0 or perp_q <= 0:
        return 0.0
    return min(spot_q, perp_q)


def estimate_unrealized_pnl(
    *,
    spot_qty: float,
    perp_qty: float,
    spot_price: float,
    perp_price: float,
    entry_spot_price: float,
    entry_perp_price: float,
) -> float:
    """Delta-neutral-ish unrealized PnL from leg price moves since entry."""
    pnl = 0.0
    if spot_qty > 0 and entry_spot_price > 0 and spot_price > 0:
        pnl += spot_qty * (spot_price - entry_spot_price)
    if perp_qty > 0 and entry_perp_price > 0 and perp_price > 0:
        pnl += perp_qty * (entry_perp_price - perp_price)
    return pnl


def accrue_funding_estimate(
    *,
    funding_rate: float,
    spot_qty: float,
    perp_qty: float,
    mark_price: float,
    hours_elapsed: float,
) -> float:
    """Rough funding accrual: rate * short notional * (hours / 8)."""
    if hours_elapsed <= 0 or mark_price <= 0:
        return 0.0
    notional = min(
        leg_notional_usdt(spot_qty, mark_price),
        leg_notional_usdt(perp_qty, mark_price),
    )
    if notional <= 0:
        notional = max(
            leg_notional_usdt(spot_qty, mark_price),
            leg_notional_usdt(perp_qty, mark_price),
        )
    if notional <= 0:
        return 0.0
    return float(funding_rate) * notional * (float(hours_elapsed) / 8.0)
