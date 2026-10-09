"""TradingExecutor tick hook for binance_btc_arb."""
from __future__ import annotations

from typing import Any, Dict

from app.services.binance_btc_arb.orchestrator import BinanceBtcArbOrchestrator
from app.utils.logger import get_logger

logger = get_logger(__name__)


def run_binance_btc_arb_tick(
    strategy_id: int,
    *,
    user_id: int,
    exchange_config: Dict[str, Any],
    trading_config: Dict[str, Any],
) -> None:
    orch = BinanceBtcArbOrchestrator(
        strategy_id=strategy_id,
        user_id=user_id,
        exchange_config=exchange_config,
        trading_config=trading_config,
    )
    try:
        orch.tick()
    except Exception as exc:
        logger.warning("binance_btc_arb tick sid=%s: %s", strategy_id, exc)
