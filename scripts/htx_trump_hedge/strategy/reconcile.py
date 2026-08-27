"""Post-exit compensation loop."""

from __future__ import annotations

import logging
import time

from htx.rest import HtxClient
from strategy.state import FSM_DONE, StrategyState, new_request_id

logger = logging.getLogger(__name__)


def is_flat(client: HtxClient, state: StrategyState, min_qty: float) -> bool:
    _, spot = client.get_spot_balance(state.currency)
    earn, _ = client.earn_total_qty(state.currency)
    perp = client.swap_short_volume(state.swap_symbol)
    return spot < min_qty and earn < min_qty and perp < min_qty


def reconcile_round(client: HtxClient, state: StrategyState, cfg: dict) -> dict:
    safety = cfg.get("safety") or {}
    min_qty = float(safety.get("min_sell_qty") or 0.01)
    max_retries = int(safety.get("max_sell_retries") or 3)

    _, spot = client.get_spot_balance(state.currency)
    earn, order_id = client.earn_total_qty(state.currency)
    perp = client.swap_short_volume(state.swap_symbol)

    snapshot = {"spot": spot, "earn": earn, "perp": perp}

    if earn >= min_qty and order_id:
        rid = new_request_id("redeem-rec")
        try:
            client.earn_redeem(order_id, f"{earn:.8f}".rstrip("0").rstrip("."), rid)
            logger.info("reconcile: redeem %.8f", earn)
        except Exception as exc:
            logger.warning("reconcile redeem failed: %s", exc)

    _, spot = client.get_spot_balance(state.currency)
    if spot >= min_qty:
        for attempt in range(max_retries):
            try:
                client.spot_market_sell(state.spot_symbol, spot, client_order_id=new_request_id(f"sell-rec-{attempt}"))
                logger.info("reconcile: sold spot %.8f", spot)
                break
            except Exception as exc:
                logger.warning("reconcile sell attempt %s failed: %s", attempt + 1, exc)
                time.sleep(0.2)

    if perp >= min_qty:
        try:
            client.swap_market_order(
                state.swap_symbol,
                side="buy",
                base_qty=perp,
                reduce_only=True,
                client_order_id=new_request_id("close-rec"),
            )
            logger.info("reconcile: close perp %.8f", perp)
        except Exception as exc:
            logger.warning("reconcile close perp failed: %s", exc)

    return snapshot


def reconcile_until_flat(client: HtxClient, state: StrategyState, cfg: dict, state_path) -> None:
    safety = cfg.get("safety") or {}
    lat = cfg.get("latency") or {}
    min_qty = float(safety.get("min_sell_qty") or 0.01)
    interval = float(lat.get("reconcile_interval_sec") or 3.0)
    max_rounds = int(lat.get("reconcile_max_rounds") or 28800)

    for i in range(max_rounds):
        snap = reconcile_round(client, state, cfg)
        logger.info("reconcile round %s: %s", i + 1, snap)
        if is_flat(client, state, min_qty):
            state.fsm = FSM_DONE
            state.save(state_path)
            logger.info("reconcile: flat, DONE")
            return
        time.sleep(interval)

    logger.error("reconcile: max rounds reached, manual check required")
