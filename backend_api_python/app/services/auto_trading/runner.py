"""TradingExecutor tick hook for bot_type=ai_auto."""
from __future__ import annotations

from typing import Any, Dict

from app.services.auto_trading.orchestrator import AiAutoOrchestrator
from app.utils.logger import get_logger

logger = get_logger(__name__)


def run_ai_auto_tick(
    strategy_id: int,
    *,
    user_id: int,
    exchange_config: Dict[str, Any],
    trading_config: Dict[str, Any],
) -> None:
    orch = AiAutoOrchestrator(
        strategy_id=strategy_id,
        user_id=user_id,
        exchange_config=exchange_config,
        trading_config=trading_config,
    )
    try:
        orch.tick()
    except Exception as e:
        logger.warning("ai_auto tick sid=%s: %s", strategy_id, e)
