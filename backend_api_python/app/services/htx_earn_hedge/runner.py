"""TradingExecutor tick hook for htx_earn_hedge."""
from __future__ import annotations

from typing import Any, Dict

from app.services.htx_earn_hedge.orchestrator import HtxEarnHedgeOrchestrator
from app.utils.logger import get_logger

logger = get_logger(__name__)


def run_htx_earn_hedge_tick(
    strategy_id: int,
    *,
    user_id: int,
    exchange_config: Dict[str, Any],
    trading_config: Dict[str, Any],
) -> None:
    orch = HtxEarnHedgeOrchestrator(
        strategy_id=strategy_id,
        user_id=user_id,
        exchange_config=exchange_config,
        trading_config=trading_config,
    )
    try:
        orch.tick()
    except Exception as exc:
        logger.warning("htx_earn_hedge tick sid=%s: %s", strategy_id, exc)
