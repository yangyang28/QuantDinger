"""LLM regime producer — outputs validated RegimeDecision only (no orders)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from app.services.auto_trading.features import collect_feature_bundle
from app.services.auto_trading.prompts import SYSTEM_PROMPT, build_user_prompt
from app.services.auto_trading.schema import (
    STRATEGY_FUNDING_CRYPTO,
    STRATEGY_GRID_BTC,
    STRATEGY_OPP_TREND,
    STRATEGY_XAU_FUNDING,
    RegimeDecision,
    default_matrix_strategies,
    parse_regime_payload,
    risk_off_fallback,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty LLM response")
    # Strip optional markdown fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        obj = json.loads(raw[start : end + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("LLM response is not a JSON object")


def _rule_based_regime(features: Dict[str, Any], primary_symbol: str) -> RegimeDecision:
    """Deterministic fallback when LLM is off or fails (PRD: AI failure → safe state)."""
    funding = 0.0
    basis = 0.0
    dim = (features.get("dimensions") or {}).get("sentiment") or {}
    fund_map = dim.get("funding") if isinstance(dim, dict) else {}
    if isinstance(fund_map, dict):
        row = fund_map.get(primary_symbol) or next(iter(fund_map.values()), None)
        if isinstance(row, dict):
            try:
                funding = float(row.get("funding_rate") or 0.0)
            except (TypeError, ValueError):
                funding = 0.0
            try:
                basis = float(row.get("basis_pct") or 0.0)
            except (TypeError, ValueError):
                basis = 0.0

    event_window = bool(((features.get("dimensions") or {}).get("event") or {}).get("window"))
    if event_window:
        return parse_regime_payload(
            {
                "regime": "RISK_OFF",
                "event_shock": "medium",
                "scores": {"technical": 0.5, "news": 0.5, "event": 0.7, "sentiment": 0.5},
                "allowed_strategies": [STRATEGY_FUNDING_CRYPTO, STRATEGY_XAU_FUNDING],
                "blocked_strategies": [STRATEGY_OPP_TREND, STRATEGY_GRID_BTC],
                "rationale_zh": "经济日历窗口内，规则回退 RISK_OFF（仅保守套利）",
                "valid_until_min": 30,
                "assets": {},
            },
            source="fallback",
        )

    # Positive funding → prefer ARBITRAGE; otherwise RANGE as default MVP
    if funding >= 0.0001 and abs(basis) <= 0.01:
        regime = "ARBITRAGE"
        allowed = [STRATEGY_FUNDING_CRYPTO, STRATEGY_XAU_FUNDING]
        rationale = f"规则：资金费率={funding:.6f} 适合费率套利"
    else:
        regime = "RANGE"
        allowed = [STRATEGY_GRID_BTC, STRATEGY_FUNDING_CRYPTO]
        rationale = f"规则：默认 RANGE（funding={funding:.6f}, basis={basis:.4%}）"

    return parse_regime_payload(
        {
            "regime": regime,
            "event_shock": "none",
            "scores": {"technical": 0.55, "news": 0.4, "event": 0.4, "sentiment": 0.5},
            "allowed_strategies": allowed,
            "blocked_strategies": [],
            "rationale_zh": rationale,
            "valid_until_min": 30,
            "assets": {
                primary_symbol.split("/")[0]: {
                    "bias": "funding_arb" if regime == "ARBITRAGE" else "neutral",
                    "confidence": 0.55,
                }
            },
        },
        source="fallback",
    )


def produce_regime(
    *,
    symbols: list,
    primary_symbol: str,
    exchange_config: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
) -> tuple[RegimeDecision, Dict[str, Any]]:
    """Return (decision, feature_bundle). Never raises — falls back to RISK_OFF/rules."""
    features = collect_feature_bundle(
        symbols=list(symbols or []),
        primary_symbol=primary_symbol,
        exchange_config=exchange_config,
    )

    if not use_llm:
        return _rule_based_regime(features, primary_symbol), features

    try:
        from app.services.llm import LLMService

        llm = LLMService()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(features)},
        ]
        text = llm.call_llm_api(messages, temperature=0.2, use_json_mode=True)
        payload = _extract_json_object(text)
        decision = parse_regime_payload(payload, source="llm")
        if not decision.allowed_strategies:
            decision.allowed_strategies = default_matrix_strategies(decision.regime)
        # Hard override: high shock → risk off for discretionary strategies
        if decision.event_shock == "high" and decision.regime != "RISK_OFF":
            decision.regime = "RISK_OFF"
            decision.blocked_strategies = list(
                set(decision.blocked_strategies) | {STRATEGY_OPP_TREND, STRATEGY_GRID_BTC}
            )
            decision.allowed_strategies = [
                s
                for s in decision.allowed_strategies
                if s in (STRATEGY_FUNDING_CRYPTO, STRATEGY_XAU_FUNDING)
            ]
            decision.rationale_zh = (decision.rationale_zh or "") + " | 高冲击强制收敛"
        return decision, features
    except Exception as e:
        logger.warning("ai_auto regime LLM failed: %s", e)
        try:
            return _rule_based_regime(features, primary_symbol), features
        except Exception as e2:
            logger.warning("ai_auto rule fallback failed: %s", e2)
            return risk_off_fallback(rationale=f"LLM/规则均失败: {e}"), features
