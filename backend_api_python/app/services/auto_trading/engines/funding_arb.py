"""Strategy A — funding arb via existing HedgeArbOrchestrator (no LLM orders)."""
from __future__ import annotations

from typing import Any, Dict

from app.services.auto_trading.config import AiAutoConfig
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log

logger = get_logger(__name__)


def run_funding_arb_engine(
    strategy_id: int,
    *,
    user_id: int,
    exchange_config: Dict[str, Any],
    trading_config: Dict[str, Any],
    cfg: AiAutoConfig,
    execute: bool,
) -> Dict[str, Any]:
    """Drive enter/exit/rebalance using hedge_arb rules when execute=True."""
    from app.services.hedge_arb.config import parse_hedge_arb_config
    from app.services.hedge_arb.orchestrator import HedgeArbOrchestrator
    from app.services.hedge_arb.signals import should_enter, should_exit
    from app.services.hedge_arb.state import HedgeArbStateRepository

    # Merge AI-auto notional into hedge config if provided
    tc = dict(trading_config or {})
    tc.setdefault("bot_type", "hedge_arb")
    tc.setdefault("symbol", cfg.primary_symbol)
    if cfg.funding_notional_usdt > 0:
        tc.setdefault("notional_usdt", cfg.funding_notional_usdt)

    orch = HedgeArbOrchestrator(
        strategy_id=strategy_id,
        user_id=user_id,
        exchange_config=exchange_config,
        trading_config=tc,
    )
    hcfg = parse_hedge_arb_config(tc)
    repo = HedgeArbStateRepository()
    state = repo.ensure_row(strategy_id, hcfg.symbol)
    signals = orch.get_signals()
    result: Dict[str, Any] = {
        "engine": "funding_arb",
        "execute": execute,
        "status": state.status,
        "funding_rate": signals.funding_rate,
        "basis_pct": signals.basis_pct,
        "action": "none",
    }

    if not execute:
        append_strategy_log(
            strategy_id,
            "info",
            f"[ai_auto/funding] observe funding={signals.funding_rate:.6f} "
            f"basis={signals.basis_pct:.4%} state={state.status}",
        )
        result["action"] = "observe"
        return result

    if state.status != "holding":
        if should_enter(
            signals,
            entry_funding_rate=hcfg.entry_funding_rate,
            max_basis_pct=hcfg.max_basis_pct,
        ):
            orch.enter()
            result["action"] = "enter"
        else:
            result["action"] = "skip_enter"
        return result

    from datetime import datetime, timezone

    hold_h = 0.0
    if state.entered_at:
        try:
            dt = datetime.fromisoformat(str(state.entered_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hold_h = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
        except Exception:
            hold_h = 0.0

    if should_exit(
        signals,
        exit_funding_rate=hcfg.exit_funding_rate,
        max_basis_pct=hcfg.max_basis_pct,
        hold_hours=hold_h,
        max_hold_hours=hcfg.max_hold_hours,
    ):
        orch.exit()
        result["action"] = "exit"
        return result

    try:
        orch.accrue_funding_tick()
    except Exception as e:
        logger.debug("funding accrual: %s", e)

    status = orch.get_status()
    drift = float(status.get("notional_drift_pct") or 0.0)
    qty_drift = float(status.get("qty_drift_pct") or 0.0)
    if drift >= hcfg.rebalance_threshold_pct or qty_drift >= hcfg.rebalance_threshold_pct:
        orch.rebalance()
        result["action"] = "rebalance"
    else:
        result["action"] = "hold"
    return result
