"""Unit tests for hedge_arb config, signals, sizing, orchestrator, and backtest."""
from __future__ import annotations

from decimal import Decimal
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
from app.services.hedge_arb.runner import _enter_skip_reason
from app.services.hedge_arb.sizing import (
    align_dual_leg_qty,
    notional_drift_pct,
    plan_entry_base_qty,
    qty_drift_metrics,
    rebalance_delta_base,
    target_base_qty,
)
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

    def test_entry_order_mode_defaults_best(self):
        cfg = parse_hedge_arb_config({"symbol": "BTC/USDT"})
        assert cfg.entry_order_mode == "best"

    def test_legacy_limit_maps_to_best(self):
        cfg = parse_hedge_arb_config({"symbol": "BTC/USDT", "order_mode": "maker"})
        assert cfg.entry_order_mode == "best"


class TestSignals:
    def test_basis(self):
        assert compute_basis_pct(100.0, 100.5) == pytest.approx(0.005)

    def test_enter_skip_reason_low_funding(self):
        sig = HedgeArbSignals("BTC/USDT", 0.00005, 100.0, 100.01, 0.0001)
        reason = _enter_skip_reason(sig, entry_funding_rate=0.0001, max_basis_pct=0.005)
        assert "funding=" in reason

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

    def test_plan_entry_rejects_small_notional(self):
        spot = MagicMock()
        perp = MagicMock()
        perp._normalize_quantity.return_value = (Decimal("0"), 3)
        spot._normalize_quantity.return_value = (Decimal("0"), 3)
        perp.get_symbol_filters.return_value = {
            "LOT_SIZE": {"minQty": "0.001", "stepSize": "0.001"},
        }
        spot.get_symbol_filters.return_value = {
            "LOT_SIZE": {"minQty": "0.00001", "stepSize": "0.00001"},
        }
        with pytest.raises(LiveTradingError, match="too small"):
            plan_entry_base_qty(
                symbol="BTC/USDT",
                notional_usdt=100,
                reference_price=50000,
                perp_client=perp,
                spot_client=spot,
            )

    def test_align_dual_leg_uses_tighter_perp_step(self):
        spot = MagicMock()
        perp = MagicMock()
        spot._normalize_quantity.return_value = (Decimal("0.00123"), 5)
        perp._normalize_quantity.return_value = (Decimal("0.001"), 3)
        aligned = align_dual_leg_qty(
            symbol="BTC/USDT",
            quantity=0.00123,
            spot_client=spot,
            perp_client=perp,
        )
        assert aligned == pytest.approx(0.001)

    def test_qty_drift_metrics_matched(self):
        gap, drift, matched = qty_drift_metrics(0.002, 0.002)
        assert gap == pytest.approx(0.0)
        assert drift == pytest.approx(0.0)
        assert matched is True

    def test_qty_drift_metrics_unmatched(self):
        gap, drift, matched = qty_drift_metrics(0.00102, 0.001)
        assert gap == pytest.approx(0.00002)
        assert drift == pytest.approx(0.02)
        assert matched is False
    @staticmethod
    def _mock_clients(*, spot_fill=0.002, perp_fill=0.002):
        spot = MagicMock()
        perp = MagicMock()
        qty = Decimal(str(spot_fill))
        spot._normalize_quantity.return_value = (qty, 3)
        perp._normalize_quantity.return_value = (qty, 3)
        spot.get_account.return_value = {
            "balances": [{"asset": "USDT", "free": "10000"}],
        }
        spot.place_best_price_order.return_value = LiveOrderResult(
            "binance", "1", spot_fill, 50000.0, {},
        )
        perp.place_best_price_order.return_value = LiveOrderResult(
            "binance", "2", perp_fill, 50000.0, {},
        )
        return spot, perp

    def _orch(self):
        return HedgeArbOrchestrator(
            strategy_id=1,
            user_id=1,
            exchange_config={"exchange_id": "binance", "api_key": "k", "secret_key": "s"},
            trading_config={
                "bot_type": "hedge_arb",
                "symbol": "BTC/USDT",
                "notional_usdt": 1000,
            },
        )

    @patch("app.services.hedge_arb.orchestrator.create_client")
    @patch("app.services.hedge_arb.orchestrator.read_live_legs")
    @patch("app.services.hedge_arb.orchestrator.HedgeArbStateRepository")
    def test_enter_success(self, repo_cls, read_legs, create_client):
        repo = repo_cls.return_value
        repo.ensure_row.return_value = MagicMock(status="flat", spot_qty=0, perp_qty=0)

        spot, perp = self._mock_clients()
        create_client.side_effect = [spot, perp]
        read_legs.return_value = (0.002, 0.002)

        orch = self._orch()
        with patch.object(orch, "get_signals") as gs:
            gs.return_value = HedgeArbSignals("BTC/USDT", 0.0002, 50000, 50010, 0.0002)
            result = orch.enter()
        assert result["ok"] is True
        assert result["spot_qty"] == pytest.approx(0.002)
        assert result["perp_qty"] == pytest.approx(0.002)
        spot_kwargs = spot.place_best_price_order.call_args.kwargs
        perp_kwargs = perp.place_best_price_order.call_args.kwargs
        assert spot_kwargs["quantity"] == perp_kwargs["quantity"]

    @patch("app.services.hedge_arb.orchestrator.create_client")
    @patch("app.services.hedge_arb.orchestrator.HedgeArbStateRepository")
    def test_enter_compensates_spot_on_perp_fail(self, repo_cls, create_client):
        repo = repo_cls.return_value
        repo.ensure_row.return_value = MagicMock(status="flat", spot_qty=0, perp_qty=0)

        spot, perp = self._mock_clients()
        perp.place_best_price_order.side_effect = LiveTradingError("perp failed")
        spot.place_market_order.return_value = LiveOrderResult(
            "binance", "3", 0.002, 50000.0, {},
        )
        create_client.side_effect = [spot, perp]
        orch = self._orch()
        with patch.object(orch, "get_signals") as gs:
            gs.return_value = HedgeArbSignals("BTC/USDT", 0.0002, 50000, 50010, 0.0002)
            with pytest.raises(LiveTradingError):
                orch.enter()
        assert spot.place_best_price_order.call_count >= 1
        assert spot.place_market_order.called

    @patch("app.services.hedge_arb.orchestrator.create_client")
    @patch("app.services.hedge_arb.orchestrator.read_live_legs")
    @patch("app.services.hedge_arb.orchestrator.HedgeArbStateRepository")
    def test_get_status_qty_fields(self, repo_cls, read_legs, create_client):
        repo = repo_cls.return_value
        repo.ensure_row.return_value = MagicMock(
            status="holding", spot_qty=0.001, perp_qty=0.001, last_error="",
            entry_basis_pct=0, entry_funding_rate=0, cumulative_funding_est=0,
            entered_at="", last_rebalance_at="",
        )
        spot, perp = self._mock_clients()
        create_client.side_effect = [spot, perp]
        read_legs.return_value = (0.00102, 0.001)

        orch = self._orch()
        with patch.object(orch, "get_signals") as gs:
            gs.return_value = HedgeArbSignals("BTC/USDT", 0.0001, 50000, 50010, 0.0001)
            status = orch.get_status()

        assert status["base_qty_gap"] == pytest.approx(0.00002)
        assert status["qty_drift_pct"] == pytest.approx(0.02)
        assert status["qty_matched"] is False

    @patch("app.services.hedge_arb.orchestrator.create_client")
    @patch("app.services.hedge_arb.orchestrator.read_live_legs")
    @patch("app.services.hedge_arb.orchestrator.HedgeArbStateRepository")
    def test_sync_trims_excess_spot(self, repo_cls, read_legs, create_client):
        spot, perp = self._mock_clients(spot_fill=0.002, perp_fill=0.001)
        create_client.side_effect = [spot, perp]
        read_legs.side_effect = [
            (0.002, 0.001),
            (0.002, 0.001),
            (0.001, 0.001),
        ]

        orch = self._orch()
        out_spot, out_perp = orch._sync_matched_base_qty(
            spot, perp, "BTC/USDT", context="ts",
        )
        assert out_spot == pytest.approx(0.001)
        assert out_perp == pytest.approx(0.001)
        assert perp.place_best_price_order.called or perp.place_market_order.called


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
