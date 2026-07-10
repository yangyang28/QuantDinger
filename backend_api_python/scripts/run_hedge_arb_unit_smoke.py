#!/usr/bin/env python3
"""Smoke-run hedge_arb unit logic without Flask/pytest (local dev fallback)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub flask so `import app.services...` does not require full stack.
if "flask" not in sys.modules:
    flask = MagicMock()
    flask.Flask = MagicMock
    sys.modules["flask"] = flask

from app.services.hedge_arb.config import parse_hedge_arb_config
from app.services.hedge_arb.exchange_adapter import normalize_exchange_id, assert_hedge_exchange_supported
from app.services.hedge_arb.signals import compute_basis_pct, should_enter, HedgeArbSignals
from app.services.hedge_arb.sizing import accrue_funding_estimate, plan_entry_quantities
from app.services.hedge_arb.exchange_adapter import HedgeExchangeContext
from app.services.live_trading.base import LiveOrderResult, LiveTradingError
from decimal import Decimal


def main() -> int:
    cfg = parse_hedge_arb_config({"symbol": "BTC/USDT", "spot_qty": 0.001, "perp_qty": 0.001})
    assert cfg.spot_qty == 0.001
    assert normalize_exchange_id("huobi") == "htx"

    sig = HedgeArbSignals("BTC/USDT", 0.0002, 50000, 50010, 0.0002)
    assert should_enter(sig, entry_funding_rate=0.0001, max_basis_pct=0.01)
    assert compute_basis_pct(100, 101) == 0.01

    spot = MagicMock()
    perp = MagicMock()
    spot._normalize_quantity.return_value = (Decimal("0.001"), 3)
    perp._normalize_quantity.return_value = (Decimal("0.001"), 3)
    ctx = HedgeExchangeContext(
        exchange_id="okx", exchange_config={}, testnet=False,
        spot_client=spot, perp_client=perp,
        spot_symbol="BTC/USDT", perp_symbol="BTC/USDT",
    )
    sq, pq, _, _ = plan_entry_quantities(ctx, spot_qty=0.001, perp_qty=0.001, reference_price=50000)
    assert sq == 0.001 and pq == 0.001

    delta = accrue_funding_estimate(
        funding_rate=0.0001, spot_qty=0.01, perp_qty=0.01, mark_price=50000, hours_elapsed=8,
    )
    assert abs(delta - 50.0) < 1e-6

    try:
        assert_hedge_exchange_supported("ibkr")
        print("FAIL: expected unsupported exchange error")
        return 1
    except LiveTradingError:
        pass

    print("hedge_arb smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
