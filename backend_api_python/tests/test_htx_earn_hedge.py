"""Tests for HTX earn hedge config and deploy helpers."""
from app.services.htx_earn_hedge.config import parse_htx_earn_hedge_config
from app.services.htx_earn_hedge.orchestrator import _expected_perp_base, _expected_spot_base
from app.services.htx_earn_hedge.sizing import alignment_metrics, plan_1to1_deploy
from app.services.live_trading.htx import HtxClient


def test_parse_htx_earn_hedge_config_defaults():
    cfg = parse_htx_earn_hedge_config({"symbol": "TRUMP/USDT", "bot_type": "htx_earn_hedge"})
    assert cfg.currency == "trump"
    assert cfg.spot_usdt == 2000
    assert cfg.perp_notional_usdt == 2000
    assert cfg.leverage == 2
    assert cfg.pre_redeem_pct == 0.005
    assert cfg.tick_interval_sec == 10
    assert cfg.align_1to1 is True


def test_parse_htx_earn_hedge_config_custom():
    cfg = parse_htx_earn_hedge_config({
        "symbol": "BTC/USDT",
        "spot_usdt": 500,
        "perp_notional_usdt": 250,
        "leverage": 3,
        "pre_redeem_pct": 0.008,
        "tick_interval_sec": 15,
    })
    assert cfg.currency == "btc"
    assert cfg.spot_usdt == 500
    assert cfg.perp_notional_usdt == 250
    assert cfg.leverage == 3
    assert cfg.pre_redeem_pct == 0.008
    assert cfg.tick_interval_sec == 15


def test_parse_capital_aliases():
    cfg = parse_htx_earn_hedge_config({
        "symbol": "TRUMP/USDT",
        "spot_capital_usdt": 1500,
        "contract_capital_usdt": 1500,
    })
    assert cfg.spot_usdt == 1500
    assert cfg.perp_notional_usdt == 1500


def test_format_earn_amount_floors_precision():
    assert HtxClient.format_earn_amount(1.234567899, precision=8) == "1.23456789"
    assert HtxClient.format_earn_amount(10.0, precision=8) == "10"
    assert HtxClient.format_earn_amount(0.000000001, precision=8) == "0"


def test_expected_deploy_base_qty():
    cfg = parse_htx_earn_hedge_config({"symbol": "TRUMP/USDT", "spot_usdt": 200, "perp_notional_usdt": 100})
    assert _expected_spot_base(cfg, 10.0) == 20.0
    assert _expected_perp_base(cfg, 10.0) == 10.0


def test_plan_1to1_equal_capitals():
    plan = plan_1to1_deploy(
        spot_usdt=2000,
        perp_notional_usdt=2000,
        price=10.0,
        spot_fee_rate=0.002,
        perp_fee_rate=0.0005,
    )
    assert plan["target_base_qty"] == 199.6  # 2000*(1-0.002)/10
    assert plan["perp_short_qty"] == 199.6
    assert plan["total_fee_est_usdt"] > 0


def test_plan_1to1_uses_min_leg():
    plan = plan_1to1_deploy(spot_usdt=3000, perp_notional_usdt=1000, price=10.0)
    assert plan["aligned_notional_usdt"] <= 1000.0 + 1e-6
    assert plan["perp_short_qty"] <= 100.0 + 1e-6


def test_alignment_metrics_matched():
    m = alignment_metrics(spot_or_earn_qty=100.0, perp_qty=100.0, price=10.0)
    assert m["qty_matched"] is True
    assert m["qty_drift_pct"] == 0.0
