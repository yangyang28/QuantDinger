"""Unit tests for hedge_arb config, signals, sizing, orchestrator, and backtest."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.broker_market_policy import BOT_TYPE_MARKETS, validate_strategy_config
from app.services.hedge_arb.backtest import simulate_funding_arb
from app.services.hedge_arb.config import parse_hedge_arb_config
from app.services.hedge_arb.orchestrator import HedgeArbOrchestrator
from app.services.hedge_arb.signals import (
    HedgeArbSignals,
    compute_basis_pct,
    should_enter,
    should_exit,
)
from app.services.hedge_arb.sizing import notional_drift_pct, rebalance_delta_base, target_base_qty
from app.services.live_trading.base import LiveOrderResult, LiveTradingError


class TestHedgeArbConfig:
    def test_defaults(self):
        cfg = parse_hedge_arb_config({"symbol": "ETH/USDT"})
        assert cfg.symbol == "ETH/USDT"
        assert len(cfg.legs) == 2
        assert cfg.legs[0].market_type == "spot"
        assert cfg.legs[1].market_type == "swap"

    def test_custom_legs(self):
        cfg = parse_hedge_arb_config({
            "symbol": "BTC/USDT",
            "hedge_legs": [
                {"market_type": "spot", "symbol": "BTC/USDT", "role": "long"},
                {"market_type": "swap", "symbol": "BTC/USDT", "role": "short"},
            ],
            "entry_funding_rate": 0.0002,
            "notional_usdt": 500,
        })
        assert cfg.entry_funding_rate == 0.0002
        assert cfg.notional_usdt == 500


class TestSignals:
    def test_basis(self):
        assert compute_basis_pct(100.0, 100.5) == pytest.approx(0.005)

    def test_should_enter(self):
        sig = HedgeArbSignals("BTC/USDT", 0.0002, 100.0, 100.1, 0.001)
        assert should_enter(sig, entry_funding_rate=0.0001, max_basis_pct=0.005)
        assert not should_enter(sig, entry_funding_rate=0.001, max_basis_pct=0.005)

    def test_should_exit(self):
        sig = HedgeArbSignals("BTC/USDT", -0.0001, 100.0, 100.0, 0.0)
        assert should_exit(sig, exit_funding_rate=0.0, max_basis_pct=0.01)


class TestSizing:
    def test_target_qty(self):
        assert target_base_qty(1000, 50000) == pytest.approx(0.02)

    def test_drift(self):
        drift = notional_drift_pct(0.02, 50000, 0.019, 50000)
        assert drift == pytest.approx(0.025641, rel=1e-3)

    def test_rebalance_delta(self):
        delta = rebalance_delta_base(0.02, 0.018, 50000, 50000)
        assert delta == pytest.approx(0.002)


class TestOrchestratorMocked:
    def _orch(self):
        return HedgeArbOrchestrator(
            strategy_id=1,
            user_id=1,
            exchange_config={"exchange_id": "binance", "api_key": "k", "secret_key": "s"},
            trading_config={
                "bot_type": "hedge_arb",
                "symbol": "BTC/USDT",
                "notional_usdt": 100,
            },
        )

    @patch("app.services.hedge_arb.orchestrator.create_client")
    @patch("app.services.hedge_arb.orchestrator.read_live_legs")
    @patch("app.services.hedge_arb.orchestrator.HedgeArbStateRepository")
    def test_enter_success(self, repo_cls, read_legs, create_client):
        repo = repo_cls.return_value
        repo.ensure_row.return_value = MagicMock(status="flat", spot_qty=0, perp_qty=0)

        spot = MagicMock()
        perp = MagicMock()
        spot.place_market_order.return_value = LiveOrderResult(
            "binance", "1", 0.002, 50000.0, {},
        )
        perp.place_market_order.return_value = LiveOrderResult(
            "binance", "2", 0.002, 50000.0, {},
        )
        create_client.side_effect = [spot, perp, spot, perp]
        read_legs.return_value = (0.002, 0.002)

        orch = self._orch()
        with patch.object(orch, "get_signals") as gs:
            gs.return_value = HedgeArbSignals("BTC/USDT", 0.0002, 50000, 50010, 0.0002)
            result = orch.enter()
        assert result["ok"] is True
        assert spot.place_market_order.called
        assert perp.place_market_order.called

    @patch("app.services.hedge_arb.orchestrator.create_client")
    @patch("app.services.hedge_arb.orchestrator.HedgeArbStateRepository")
    def test_enter_compensates_spot_on_perp_fail(self, repo_cls, create_client):
        repo = repo_cls.return_value
        repo.ensure_row.return_value = MagicMock(status="flat", spot_qty=0, perp_qty=0)

        spot = MagicMock()
        perp = MagicMock()
        spot.place_market_order.side_effect = [
            LiveOrderResult("binance", "1", 0.002, 50000.0, {}),
            LiveOrderResult("binance", "3", 0.002, 50000.0, {}),
        ]
        perp.place_market_order.side_effect = LiveTradingError("perp failed")

        create_client.side_effect = [spot, perp, spot, perp]
        orch = self._orch()
        with patch.object(orch, "get_signals") as gs:
            gs.return_value = HedgeArbSignals("BTC/USDT", 0.0002, 50000, 50010, 0.0002)
            with pytest.raises(LiveTradingError):
                orch.enter()
        assert spot.place_market_order.call_count >= 2


class TestBacktest:
    @patch("app.services.hedge_arb.backtest.fetch_historical_funding")
    def test_simulate_cycles(self, fetch_hist):
        fetch_hist.return_value = [
            {"funding_time_ms": 1, "funding_rate": 0.0002},
            {"funding_time_ms": 2, "funding_rate": 0.00015},
            {"funding_time_ms": 3, "funding_rate": -0.0001},
        ]
        out = simulate_funding_arb(
            "BTC/USDT",
            notional_usdt=1000,
            entry_funding_rate=0.0001,
            exit_funding_rate=0.0,
        )
        assert out["cycles"] == 1
        assert out["funding_pnl_usdt"] == pytest.approx(1000 * (0.0002 + 0.00015))
        assert out["fee_cost_usdt"] > 0


class TestBrokerPolicy:
    def test_hedge_arb_crypto_only(self):
        assert "Crypto" in BOT_TYPE_MARKETS["hedge_arb"]
        validate_strategy_config(
            exchange_id="binance",
            market_category="Crypto",
            market_type="swap",
            bot_type="hedge_arb",
        )

    def test_hedge_arb_rejects_usstock(self):
        with pytest.raises(ValueError, match="hedge_arb"):
            validate_strategy_config(
                exchange_id="ibkr",
                market_category="USStock",
                market_type="spot",
                bot_type="hedge_arb",
            )
