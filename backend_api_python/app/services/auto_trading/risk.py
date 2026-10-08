"""Hard risk gates — cannot be overridden by the model (PRD §2 / §7)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.services.auto_trading.config import AiAutoConfig
from app.services.auto_trading.schema import (
    STRATEGY_GRID_BTC,
    STRATEGY_OPP_TREND,
    RegimeDecision,
)


@dataclass
class RiskGateResult:
    ok: bool
    reason: str = ""
    force_risk_off: bool = False
    filtered_allowed: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "force_risk_off": self.force_risk_off,
            "filtered_allowed": list(self.filtered_allowed or []),
        }


def apply_risk_gates(
    decision: RegimeDecision,
    cfg: AiAutoConfig,
    *,
    daily_loss_pct: float = 0.0,
) -> RiskGateResult:
    if cfg.kill_switch:
        return RiskGateResult(
            ok=False,
            reason="kill_switch=true",
            force_risk_off=True,
            filtered_allowed=[],
        )

    if daily_loss_pct <= -abs(cfg.max_daily_loss_pct):
        return RiskGateResult(
            ok=False,
            reason=f"daily_loss={daily_loss_pct:.2%} breached max={cfg.max_daily_loss_pct:.2%}",
            force_risk_off=True,
            filtered_allowed=[],
        )

    allowed = [s for s in decision.allowed_strategies if s not in set(decision.blocked_strategies)]

    if decision.event_shock == "high" or decision.regime == "RISK_OFF":
        # Discretionary strategies blocked; funding arb may remain if listed
        allowed = [s for s in allowed if s not in (STRATEGY_OPP_TREND, STRATEGY_GRID_BTC)]
        if decision.regime == "RISK_OFF" and decision.event_shock == "high":
            return RiskGateResult(
                ok=True,
                reason="RISK_OFF/high shock — discretionary blocked",
                filtered_allowed=allowed,
            )

    if not cfg.enable_funding_arb:
        allowed = [s for s in allowed if "FUNDING" not in s]
    if not cfg.enable_opportunity:
        allowed = [s for s in allowed if s != STRATEGY_OPP_TREND]
    if not cfg.enable_grid:
        allowed = [s for s in allowed if s != STRATEGY_GRID_BTC]

    return RiskGateResult(ok=True, reason="pass", filtered_allowed=allowed)
