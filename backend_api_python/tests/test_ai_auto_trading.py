"""Unit tests for AI auto-trading regime schema / risk / router."""
from __future__ import annotations

from app.services.auto_trading.config import parse_ai_auto_config
from app.services.auto_trading.risk import apply_risk_gates
from app.services.auto_trading.router import build_engine_plan
from app.services.auto_trading.schema import (
    STRATEGY_FUNDING_CRYPTO,
    STRATEGY_GRID_BTC,
    STRATEGY_OPP_TREND,
    parse_regime_payload,
    risk_off_fallback,
)


def test_parse_regime_payload_ok():
    d = parse_regime_payload(
        {
            "regime": "RANGE",
            "event_shock": "low",
            "scores": {"technical": 0.6, "news": 0.4, "event": 0.5, "sentiment": 0.3},
            "assets": {"BTC": {"bias": "neutral", "box": [82000, 85000], "confidence": 0.7}},
            "allowed_strategies": [STRATEGY_GRID_BTC, STRATEGY_FUNDING_CRYPTO],
            "blocked_strategies": [STRATEGY_OPP_TREND],
            "rationale_zh": "箱体震荡",
            "valid_until_min": 30,
        }
    )
    assert d.regime == "RANGE"
    assert "BTC" in d.assets
    assert d.assets["BTC"].box == [82000.0, 85000.0]


def test_parse_regime_rejects_bad_regime():
    try:
        parse_regime_payload({"regime": "YOLO"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_risk_kill_switch():
    cfg = parse_ai_auto_config({"kill_switch": True, "bot_type": "ai_auto"})
    d = risk_off_fallback(rationale="test")
    gate = apply_risk_gates(d, cfg)
    assert gate.ok is False
    assert gate.force_risk_off is True


def test_router_range_enables_grid():
    cfg = parse_ai_auto_config(
        {
            "bot_type": "ai_auto",
            "human_mode": "observe",
            "enable_grid": True,
            "enable_funding_arb": True,
            "enable_opportunity": True,
        }
    )
    d = parse_regime_payload(
        {
            "regime": "RANGE",
            "event_shock": "none",
            "allowed_strategies": [STRATEGY_GRID_BTC, STRATEGY_FUNDING_CRYPTO],
            "scores": {"technical": 0.5, "news": 0.5, "event": 0.5, "sentiment": 0.5},
        }
    )
    gate = apply_risk_gates(d, cfg)
    plan = build_engine_plan(d, cfg, gate.filtered_allowed or [])
    assert plan.run_grid is True
    assert plan.run_funding_arb is True
    assert plan.run_opportunity is False


def test_high_shock_blocks_discretionary():
    cfg = parse_ai_auto_config({"bot_type": "ai_auto"})
    d = parse_regime_payload(
        {
            "regime": "TREND",
            "event_shock": "high",
            "allowed_strategies": [STRATEGY_OPP_TREND, STRATEGY_GRID_BTC, STRATEGY_FUNDING_CRYPTO],
            "scores": {"technical": 0.5, "news": 0.5, "event": 0.9, "sentiment": 0.5},
        }
    )
    gate = apply_risk_gates(d, cfg)
    assert STRATEGY_OPP_TREND not in (gate.filtered_allowed or [])
    assert STRATEGY_GRID_BTC not in (gate.filtered_allowed or [])
