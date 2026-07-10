"""Optional Binance testnet integration for hedge-arb dual-leg flow."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.services.hedge_arb.exchange_adapter import HedgeExchangeContext, read_live_legs
from app.services.hedge_arb.orchestrator import HedgeArbOrchestrator
from app.services.hedge_arb.signals import collect_signals
from app.services.hedge_arb.sizing import notional_drift_pct
from app.services.live_trading.factory import create_client


pytestmark = pytest.mark.integration


def _live_enabled() -> bool:
    return os.getenv("RUN_HEDGE_ARB_LIVE_TESTS", "").strip().lower() in ("1", "true", "yes")


def _spot_cfg() -> dict:
    return {
        "exchange_id": "binance",
        "api_key": os.getenv("HEDGE_ARB_LIVE_BINANCE_SPOT_API_KEY", ""),
        "secret_key": os.getenv("HEDGE_ARB_LIVE_BINANCE_SPOT_SECRET", ""),
        "enable_demo_trading": True,
    }


def _futures_cfg() -> dict:
    return {
        "exchange_id": "binance",
        "api_key": os.getenv("HEDGE_ARB_LIVE_BINANCE_FUTURES_API_KEY", ""),
        "secret_key": os.getenv("HEDGE_ARB_LIVE_BINANCE_FUTURES_SECRET", ""),
        "enable_demo_trading": True,
    }


def _build_test_ctx(symbol: str) -> HedgeExchangeContext:
    spot_cfg = _spot_cfg()
    fut_cfg = _futures_cfg()
    return HedgeExchangeContext(
        exchange_id="binance",
        exchange_config=fut_cfg,
        testnet=True,
        spot_client=create_client(spot_cfg, market_type="spot"),
        perp_client=create_client(fut_cfg, market_type="swap"),
        spot_symbol=symbol,
        perp_symbol=symbol,
    )


@pytest.mark.skipif(not _live_enabled(), reason="Set RUN_HEDGE_ARB_LIVE_TESTS=1 and testnet keys")
class TestHedgeArbLiveTestnet:
    SYMBOL = "BTC/USDT"
    NOTIONAL = float(os.getenv("HEDGE_ARB_LIVE_NOTIONAL_USDT", "120"))

    def test_public_signals_testnet(self):
        sig = collect_signals(self.SYMBOL, exchange_id="binance", testnet=True)
        assert sig.spot_price > 0
        assert sig.perp_mark_price > 0

    def test_dual_leg_enter_exit_smoke(self):
        spot_cfg = _spot_cfg()
        fut_cfg = _futures_cfg()
        if not spot_cfg["api_key"] or not fut_cfg["api_key"]:
            pytest.skip("Missing HEDGE_ARB_LIVE_BINANCE_* testnet keys in env")

        ref_price = collect_signals(self.SYMBOL, exchange_id="binance", testnet=True).spot_price
        qty = max(0.001, self.NOTIONAL / ref_price) if ref_price > 0 else 0.001

        orch = HedgeArbOrchestrator(
            strategy_id=999999,
            user_id=1,
            exchange_config=fut_cfg,
            trading_config={
                "bot_type": "hedge_arb",
                "symbol": self.SYMBOL,
                "spot_qty": qty,
                "perp_qty": qty,
            },
        )

        ctx = _build_test_ctx(self.SYMBOL)
        with patch("app.services.hedge_arb.orchestrator.build_hedge_context", return_value=ctx):
            status_before = orch.get_status()
            assert "signals" in status_before

            try:
                orch.exit()
            except Exception:
                pass

            enter = orch.enter(spot_qty=qty, perp_qty=qty)
            assert enter.get("ok") is True

            spot_qty, perp_qty = read_live_legs(ctx)
            assert spot_qty > 0
            assert perp_qty > 0

            sig = collect_signals(self.SYMBOL, exchange_id="binance", testnet=True)
            drift = notional_drift_pct(spot_qty, sig.spot_price, perp_qty, sig.perp_mark_price)
            assert drift < 0.15

            exit_res = orch.exit()
            assert exit_res.get("ok") is True
