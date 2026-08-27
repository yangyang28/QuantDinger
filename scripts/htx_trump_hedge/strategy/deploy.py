"""One-shot deploy: buy spot, 100% earn, open short."""

from __future__ import annotations

import logging
import time

from htx.rest import HtxClient
from strategy.state import FSM_ARMED, StrategyState, new_request_id

logger = logging.getLogger(__name__)


def deploy(
    client: HtxClient,
    cfg: dict,
    state: StrategyState,
    state_path,
) -> StrategyState:
    if state.deployed_at > 0 and state.fsm not in ("DONE",):
        raise RuntimeError(
            f"already deployed (fsm={state.fsm}). "
            "Use emergency-exit first or delete state.json before re-deploy."
        )

    strat = cfg["strategy"]
    spot_symbol = strat["spot_symbol"]
    swap_symbol = strat["swap_symbol"]
    currency = strat["currency"].lower()
    spot_usdt = float(strat["spot_usdt"])
    perp_notional = float(strat["perp_notional_usdt"])
    leverage = int(strat["leverage"])

    logger.info("deploy: spot buy %.2f USDT %s", spot_usdt, spot_symbol)
    price = client.spot_ticker(spot_symbol)
    if price <= 0:
        raise RuntimeError("cannot fetch spot price")

    client.spot_market_buy_usdt(spot_symbol, spot_usdt, client_order_id=new_request_id("buy"))
    time.sleep(1.5)

    _, avail = client.get_spot_balance(currency)
    if avail <= 0:
        _, avail = client.get_spot_balance(currency)
    if avail <= 0:
        raise RuntimeError(f"no {currency} balance after spot buy")

    earn_qty = avail
    logger.info("deploy: subscribe earn 100%% qty=%.8f", earn_qty)
    project = client.earn_find_flexible_project(currency)
    project_id = int(project.get("id") or project.get("projectId") or 0)
    if project_id <= 0:
        raise RuntimeError("earn project id not found")

    sub = client.earn_subscribe(project_id, f"{earn_qty:.8f}".rstrip("0").rstrip("."), new_request_id("sub"))
    logger.info("earn subscribe response: %s", sub)

    time.sleep(1.0)
    earn_total, order_id = client.earn_total_qty(currency)
    if order_id is None:
        assets = client.earn_user_assets(currency)
        if assets:
            order_id = int(assets[0].get("orderId") or 0) or None

    perp_qty = perp_notional / price if price > 0 else 0.0
    logger.info("deploy: open short notional=%.2f base_qty≈%.8f leverage=%dx", perp_notional, perp_qty, leverage)
    client.swap_set_leverage(swap_symbol, leverage)
    client.swap_market_order(swap_symbol, side="sell", base_qty=perp_qty, client_order_id=new_request_id("short"))

    state.spot_symbol = spot_symbol
    state.swap_symbol = swap_symbol
    state.currency = currency
    state.spot_account_id = client.get_spot_account_id()
    state.earn_order_id = order_id
    state.earn_qty = earn_total or earn_qty
    state.perp_qty = client.swap_short_volume(swap_symbol) or perp_qty
    state.leverage = leverage
    state.fsm = FSM_ARMED
    state.pre_redeemed = False
    state.redeem_sent = False
    state.redeem_request_id = ""
    state.last_perp_qty = state.perp_qty
    state.deployed_at = time.time()
    state.save(state_path)
    logger.info("deploy done: earn_qty=%.8f perp_qty=%.8f order_id=%s", state.earn_qty, state.perp_qty, state.earn_order_id)
    return state
