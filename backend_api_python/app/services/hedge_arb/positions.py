"""Read spot / perp leg sizes via multi-exchange position query."""
from __future__ import annotations

from typing import Tuple

from app.services.hedge_arb.exchange_adapter import HedgeExchangeContext, read_live_legs as _read_live_legs
from app.services.live_trading.position_query import query_exchange_position_size


def read_live_legs(ctx: HedgeExchangeContext) -> Tuple[float, float]:
    return _read_live_legs(ctx)


def spot_base_balance(ctx: HedgeExchangeContext) -> float:
    return query_exchange_position_size(
        client=ctx.spot_client,
        symbol=ctx.spot_symbol,
        pos_side="long",
        market_type="spot",
        exchange_config=ctx.exchange_config,
    )
