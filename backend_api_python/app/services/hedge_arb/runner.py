"""TradingExecutor tick hook for hedge_arb bot_type."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.hedge_arb.config import parse_hedge_arb_config
from app.services.hedge_arb.orchestrator import HedgeArbOrchestrator
from app.services.hedge_arb.signals import should_enter, should_exit
from app.services.hedge_arb.state import HedgeArbStateRepository
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log

logger = get_logger(__name__)


def _hold_hours(entered_at: Optional[str]) -> float:
    if not entered_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(entered_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def _enter_skip_reason(
    signals,
    *,
    entry_funding_rate: float,
    max_basis_pct: float,
) -> str:
    parts: list[str] = []
    if signals.funding_rate < entry_funding_rate:
        parts.append(
            f"funding={signals.funding_rate:.6f} < entry={entry_funding_rate:.6f}"
        )
    if max_basis_pct > 0 and abs(signals.basis_pct) > max_basis_pct:
        parts.append(
            f"|basis|={abs(signals.basis_pct):.4%} > max={max_basis_pct:.4%}"
        )
    if signals.spot_price <= 0 or signals.perp_mark_price <= 0:
        parts.append("missing spot/perp price")
    return "; ".join(parts) if parts else "conditions not met"


def run_hedge_arb_tick(
    strategy_id: int,
    *,
    user_id: int,
    exchange_config: Dict[str, Any],
    trading_config: Dict[str, Any],
) -> None:
    """Evaluate funding/basis and drive enter / exit / rebalance for one strategy."""
    cfg = parse_hedge_arb_config(trading_config)
    orch = HedgeArbOrchestrator(
        strategy_id=strategy_id,
        user_id=user_id,
        exchange_config=exchange_config,
        trading_config=trading_config,
    )
    repo = HedgeArbStateRepository()
    state = repo.ensure_row(strategy_id, cfg.symbol)
    signals = orch.get_signals()

    if state.status != "holding":
        if should_enter(
            signals,
            entry_funding_rate=cfg.entry_funding_rate,
            max_basis_pct=cfg.max_basis_pct,
        ):
            try:
                orch.enter()
            except Exception as e:
                logger.warning("hedge_arb enter sid=%s: %s", strategy_id, e)
        else:
            append_strategy_log(
                strategy_id,
                "info",
                f"Hedge flat — skip enter: {_enter_skip_reason(signals, entry_funding_rate=cfg.entry_funding_rate, max_basis_pct=cfg.max_basis_pct)}",
            )
        return

    hold_h = _hold_hours(state.entered_at)
    if should_exit(
        signals,
        exit_funding_rate=cfg.exit_funding_rate,
        max_basis_pct=cfg.max_basis_pct,
        hold_hours=hold_h,
        max_hold_hours=cfg.max_hold_hours,
    ):
        try:
            orch.exit()
        except Exception as e:
            logger.warning("hedge_arb exit sid=%s: %s", strategy_id, e)
        return

    status = orch.get_status()
    drift = float(status.get("notional_drift_pct") or 0.0)
    qty_drift = float(status.get("qty_drift_pct") or 0.0)
    try:
        orch.accrue_funding_tick()
    except Exception as e:
        logger.debug("hedge_arb funding accrual sid=%s: %s", strategy_id, e)
    if drift >= cfg.rebalance_threshold_pct or qty_drift >= cfg.rebalance_threshold_pct:
        try:
            orch.rebalance()
        except Exception as e:
            logger.warning("hedge_arb rebalance sid=%s: %s", strategy_id, e)
    else:
        append_strategy_log(
            strategy_id,
            "debug",
            f"Hedge hold funding={signals.funding_rate:.6f} basis={signals.basis_pct:.4%} "
            f"notional_drift={drift:.2%} qty_drift={qty_drift:.2%}",
        )
