"""Tests for Binance BTC arb config and sizing."""
from app.services.binance_btc_arb.config import parse_binance_btc_arb_config
from app.services.binance_btc_arb.sizing import alignment_metrics, plan_1to1_deploy


def test_parse_binance_btc_arb_config_defaults():
    cfg = parse_binance_btc_arb_config({"symbol": "BTC/USDT", "bot_type": "binance_btc_arb"})
    assert cfg.currency == "btc"
    assert cfg.symbol == "BTC/USDT"
    assert cfg.spot_usdt == 2000
    assert cfg.perp_notional_usdt == 2000
    assert cfg.leverage == 2
    assert cfg.pre_exit_pct == 0.005
    assert cfg.tick_interval_sec == 10
    assert cfg.align_1to1 is True


def test_parse_binance_btc_arb_config_custom():
    cfg = parse_binance_btc_arb_config({
        "symbol": "BTC/USDT",
        "spot_usdt": 500,
        "perp_notional_usdt": 250,
        "leverage": 3,
        "pre_exit_pct": 0.008,
        "tick_interval_sec": 15,
    })
    assert cfg.spot_usdt == 500
    assert cfg.perp_notional_usdt == 250
    assert cfg.leverage == 3
    assert cfg.pre_exit_pct == 0.008
    assert cfg.tick_interval_sec == 15


def test_plan_1to1_btc_deploy():
    plan = plan_1to1_deploy(
        spot_usdt=2000,
        perp_notional_usdt=2000,
        price=50000.0,
        spot_fee_rate=0.001,
        perp_fee_rate=0.0005,
    )
    assert plan["target_base_qty"] > 0
    assert plan["perp_short_qty"] == plan["target_base_qty"]
    assert plan["total_fee_est_usdt"] > 0


def test_alignment_metrics_matched():
    m = alignment_metrics(spot_or_earn_qty=0.01, perp_qty=0.01, price=50000.0)
    assert m["qty_matched"] is True
    assert m["spot_notional_usdt"] == 500.0
