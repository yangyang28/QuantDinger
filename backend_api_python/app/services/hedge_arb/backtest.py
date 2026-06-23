"""Approximate funding-arb backtest using Binance historical funding rates."""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.hedge_arb.signals import fetch_historical_funding


def simulate_funding_arb(
    symbol: str,
    *,
    notional_usdt: float = 1000.0,
    entry_funding_rate: float = 0.0001,
    exit_funding_rate: float = 0.0,
    taker_fee_rate: float = 0.0004,
    limit: int = 500,
    testnet: bool = False,
) -> Dict[str, Any]:
    """
    Simple backtest: enter when funding >= entry threshold, exit when < exit.
    PnL = sum(funding * notional) - round-trip taker fees (4 legs max per cycle).
    """
    history = fetch_historical_funding(symbol, limit=limit, testnet=testnet)
    if not history:
        return {
            "symbol": symbol,
            "periods": 0,
            "cycles": 0,
            "net_pnl_usdt": 0.0,
            "funding_pnl_usdt": 0.0,
            "fee_cost_usdt": 0.0,
            "events": [],
        }

    holding = False
    cycles = 0
    funding_pnl = 0.0
    fee_cost = 0.0
    events: List[Dict[str, Any]] = []

    for row in history:
        rate = float(row.get("funding_rate") or 0.0)
        ts = int(row.get("funding_time_ms") or 0)
        if not holding:
            if rate >= entry_funding_rate:
                holding = True
                cycles += 1
                fee_cost += notional_usdt * taker_fee_rate * 2
                events.append({"ts": ts, "action": "enter", "funding_rate": rate})
            continue

        funding_pnl += notional_usdt * rate
        if rate < exit_funding_rate:
            holding = False
            fee_cost += notional_usdt * taker_fee_rate * 2
            events.append({"ts": ts, "action": "exit", "funding_rate": rate})

    return {
        "symbol": symbol,
        "periods": len(history),
        "cycles": cycles,
        "net_pnl_usdt": funding_pnl - fee_cost,
        "funding_pnl_usdt": funding_pnl,
        "fee_cost_usdt": fee_cost,
        "holding_at_end": holding,
        "events": events[-20:],
    }
