"""Tests for HTX earn hedge config parsing."""
from app.services.htx_earn_hedge.config import parse_htx_earn_hedge_config


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
