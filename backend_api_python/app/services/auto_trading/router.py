"""Map validated regime + risk filters → engine action plan (PRD §5.4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.services.auto_trading.config import AiAutoConfig
from app.services.auto_trading.schema import (
    STRATEGY_FUNDING_CRYPTO,
    STRATEGY_GRID_BTC,
    STRATEGY_OPP_TREND,
    STRATEGY_XAU_FUNDING,
    RegimeDecision,
)


@dataclass
class EnginePlan:
    run_funding_arb: bool = False
    run_opportunity: bool = False
    run_grid: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_funding_arb": self.run_funding_arb,
            "run_opportunity": self.run_opportunity,
            "run_grid": self.run_grid,
            "reasons": list(self.reasons),
        }


def build_engine_plan(
    decision: RegimeDecision,
    cfg: AiAutoConfig,
    allowed: List[str],
) -> EnginePlan:
    allowed_set = set(allowed or [])
    plan = EnginePlan()

    funding_tags = {STRATEGY_FUNDING_CRYPTO, STRATEGY_XAU_FUNDING}
    if cfg.enable_funding_arb and (allowed_set & funding_tags):
        # Also allow ARBITRAGE / RANGE / TREND matrix even if LLM forgot tags
        if decision.regime in ("ARBITRAGE", "RANGE", "TREND", "RISK_OFF"):
            plan.run_funding_arb = True
            plan.reasons.append("funding_arb allowed by regime matrix")

    if cfg.enable_opportunity and STRATEGY_OPP_TREND in allowed_set and decision.regime == "TREND":
        plan.run_opportunity = True
        plan.reasons.append("opportunity enabled in TREND")

    if cfg.enable_grid and STRATEGY_GRID_BTC in allowed_set and decision.regime == "RANGE":
        plan.run_grid = True
        plan.reasons.append("grid enabled in RANGE")

    if cfg.human_mode == "observe":
        # Still compute plan for logging, but orchestrator will not execute live legs
        plan.reasons.append("human_mode=observe (no live orders)")

    return plan
