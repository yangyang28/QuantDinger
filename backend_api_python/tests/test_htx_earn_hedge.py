"""Tests for HTX earn hedge config and deploy helpers."""
from app.services.htx_earn_hedge.config import parse_htx_earn_hedge_config
from app.services.htx_earn_hedge.orchestrator import _expected_perp_base, _expected_spot_base
from app.services.live_trading.htx import HtxClient


def test_parse_htx_earn_hedge_config_defaults():
    cfg = parse_htx_earn_hedge_config({"symbol": "TRUMP/USDT", "bot_type": "htx_earn_hedge"})
    assert cfg.currency == "trump"
    assert cfg.spot_usdt == 200
    assert cfg.perp_notional_usdt == 100
    assert cfg.leverage == 2
    assert cfg.pre_redeem_pct == 0.005
    assert cfg.tick_interval_sec == 10


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


def test_format_earn_amount_floors_precision():
    assert HtxClient.format_earn_amount(1.234567899, precision=8) == "1.23456789"
    assert HtxClient.format_earn_amount(10.0, precision=8) == "10"
    assert HtxClient.format_earn_amount(0.000000001, precision=8) == "0"


def test_expected_deploy_base_qty():
    cfg = parse_htx_earn_hedge_config({"symbol": "TRUMP/USDT", "spot_usdt": 200, "perp_notional_usdt": 100})
    assert _expected_spot_base(cfg, 10.0) == 20.0
    assert _expected_perp_base(cfg, 10.0) == 10.0
