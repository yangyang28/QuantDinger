"""Exit state machine: pre-redeem near liquidation, sell on forced liquidation."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from htx.rest import HtxClient, HtxError
from strategy.reconcile import is_flat, reconcile_until_flat
from strategy.state import (
    FSM_ARMED,
    FSM_DONE,
    FSM_LIQUIDATED_FALLBACK,
    FSM_LIQUIDATED_FAST,
    FSM_PRE_REDEEMED,
    FSM_PRE_REDEEMING,
    FSM_RECONCILING,
    StrategyState,
    new_request_id,
)

logger = logging.getLogger(__name__)

UTC8 = timezone(timedelta(hours=8))


def _log_event(event: str, **kwargs) -> None:
    payload = {"event": event, **kwargs}
    logger.info("%s", payload)


def _dist_to_liq_pct(mark: float, liq: float, *, is_short: bool) -> float:
    """Positive when mark has NOT reached liq yet (room before liquidation)."""
    if mark <= 0 or liq <= 0:
        return 1.0
    if is_short:
        # short liquidates when mark rises toward liq
        return (liq - mark) / liq
    return (mark - liq) / liq


def _in_redeem_maintenance(cfg: dict) -> bool:
    hours = (cfg.get("safety") or {}).get("redeem_maintenance_utc8_hours") or [0]
    now = datetime.now(UTC8)
    return now.hour in hours


def wait_trump_available(
    client: HtxClient,
    state: StrategyState,
    cfg: dict,
    target: float,
) -> float:
    lat = cfg.get("latency") or {}
    poll_ms = int(lat.get("balance_poll_interval_ms") or 80)
    max_ms = int(lat.get("balance_poll_max_ms") or 1200)
    min_qty = float((cfg.get("safety") or {}).get("min_sell_qty") or 0.01)
    need = max(target * 0.99, min_qty)
    deadline = time.time() + max_ms / 1000.0
    while time.time() < deadline:
        _, avail = client.get_spot_balance(state.currency)
        if avail >= need:
            _log_event("balance_ready", available=avail, latency_ms=int((max_ms / 1000 - (deadline - time.time())) * 1000))
            return avail
        time.sleep(poll_ms / 1000.0)
    _, avail = client.get_spot_balance(state.currency)
    return avail


def _sell_spot_with_retry(client: HtxClient, state: StrategyState, cfg: dict, qty: float) -> None:
    safety = cfg.get("safety") or {}
    min_qty = float(safety.get("min_sell_qty") or 0.01)
    retries = int(safety.get("max_sell_retries") or 3)
    if qty < min_qty:
        return
    for i in range(retries):
        try:
            oid = client.spot_market_sell(
                state.spot_symbol,
                qty,
                client_order_id=new_request_id(f"sell-{i}"),
            )
            _log_event("spot_sold", qty=qty, order_id=oid, attempt=i + 1)
            return
        except HtxError as exc:
            logger.warning("spot sell attempt %s failed: %s", i + 1, exc)
            time.sleep(0.15)


def _ensure_perp_flat(client: HtxClient, state: StrategyState) -> None:
    perp = client.swap_short_volume(state.swap_symbol)
    if perp <= 0:
        return
    try:
        oid = client.swap_market_order(
            state.swap_symbol,
            side="buy",
            base_qty=perp,
            reduce_only=True,
            client_order_id=new_request_id("close"),
        )
        _log_event("perp_close_sent", qty=perp, order_id=oid)
    except HtxError as exc:
        logger.warning("perp close failed (may already be liquidated): %s", exc)


def _start_redeem(client: HtxClient, state: StrategyState, cfg: dict) -> bool:
    if state.redeem_sent:
        return True
    earn, order_id = client.earn_total_qty(state.currency)
    if earn <= 0 and state.pre_redeemed:
        state.pre_redeemed = True
        return True
    oid = order_id or state.earn_order_id
    if not oid:
        assets = client.earn_user_assets(state.currency)
        if assets:
            oid = int(assets[0].get("orderId") or 0) or None
    if not oid:
        logger.warning("no earn order_id for redeem")
        return False
    qty = earn if earn > 0 else state.earn_qty
    if qty <= 0:
        return False
    if not state.redeem_request_id:
        state.redeem_request_id = new_request_id("redeem")
    try:
        client.earn_redeem(int(oid), f"{qty:.8f}".rstrip("0").rstrip("."), state.redeem_request_id)
        state.redeem_sent = True
        state.earn_qty = qty
        state.earn_order_id = int(oid)
        _log_event("redeem_sent", qty=qty, order_id=oid, request_id=state.redeem_request_id)
        return True
    except HtxError as exc:
        logger.warning("redeem failed: %s", exc)
        return False


def _confirm_pre_redeemed(client: HtxClient, state: StrategyState, cfg: dict) -> bool:
    avail = wait_trump_available(client, state, cfg, state.earn_qty)
    min_qty = float((cfg.get("safety") or {}).get("min_sell_qty") or 0.01)
    if avail >= max(state.earn_qty * 0.99, min_qty):
        state.pre_redeemed = True
        state.fsm = FSM_PRE_REDEEMED
        _log_event("pre_redeemed_ready", available=avail)
        return True
    earn, _ = client.earn_total_qty(state.currency)
    if earn < min_qty and avail >= min_qty:
        state.pre_redeemed = True
        state.fsm = FSM_PRE_REDEEMED
        state.earn_qty = avail
        return True
    return False


def on_liquidation(client: HtxClient, state: StrategyState, cfg: dict, state_path, *, pre_redeemed: bool) -> None:
    t0 = time.time()
    path = "fast" if pre_redeemed else "fallback"
    _log_event("liquidation_detected", pre_redeemed=pre_redeemed, path=path)

    if pre_redeemed:
        state.fsm = FSM_LIQUIDATED_FAST
        state.save(state_path)
        _, avail = client.get_spot_balance(state.currency)
        _sell_spot_with_retry(client, state, cfg, avail)
        _ensure_perp_flat(client, state)
    else:
        state.fsm = FSM_LIQUIDATED_FALLBACK
        state.save(state_path)
        _start_redeem(client, state, cfg)
        _ensure_perp_flat(client, state)
        avail = wait_trump_available(client, state, cfg, state.earn_qty)
        if avail > 0:
            _sell_spot_with_retry(client, state, cfg, avail)
        else:
            _, spot = client.get_spot_balance(state.currency)
            _sell_spot_with_retry(client, state, cfg, spot)

    state.fsm = FSM_RECONCILING
    state.save(state_path)
    _log_event("exit_done", total_ms=int((time.time() - t0) * 1000), path=path)
    reconcile_until_flat(client, state, cfg, state_path)


def maybe_pre_redeem(client: HtxClient, state: StrategyState, cfg: dict, state_path, dist_pct: float) -> None:
    th = cfg.get("thresholds") or {}
    pre_pct = float(th.get("pre_redeem_pct") or 0.005)
    emerg_pct = float(th.get("emergency_redeem_pct") or 0.0025)
    maint_pct = float(th.get("maintenance_pre_redeem_pct") or 0.01)

    trigger_pct = pre_pct
    if _in_redeem_maintenance(cfg):
        trigger_pct = max(trigger_pct, maint_pct)
        _log_event("maintenance_window", using_pct=trigger_pct)

    should = dist_pct <= trigger_pct
    if not should and not state.pre_redeemed and dist_pct <= emerg_pct:
        should = True
        _log_event("emergency_pre_redeem", dist_pct=dist_pct)

    if not should or state.pre_redeemed or state.fsm != FSM_ARMED:
        if state.fsm == FSM_PRE_REDEEMING:
            if _confirm_pre_redeemed(client, state, cfg):
                state.save(state_path)
        return

    _log_event("soft_redeem_trigger", dist_pct=dist_pct, threshold=trigger_pct)
    state.fsm = FSM_PRE_REDEEMING
    state.save(state_path)
    if _start_redeem(client, state, cfg):
        if _confirm_pre_redeemed(client, state, cfg):
            state.save(state_path)


def poll_interval(cfg: dict, dist_pct: float) -> float:
    lat = cfg.get("latency") or {}
    th = cfg.get("thresholds") or {}
    watch = float(th.get("watch_poll_pct") or 0.02)
    pre = float(th.get("pre_redeem_pct") or 0.005)
    if dist_pct <= pre:
        return float(lat.get("poll_interval_critical_sec") or 0.1)
    if dist_pct <= watch:
        return float(lat.get("poll_interval_watch_sec") or 0.5)
    return float(lat.get("poll_interval_normal_sec") or 2.0)


def detect_liquidation(state: StrategyState, current_perp: float) -> bool:
    prev = float(state.last_perp_qty or 0)
    if prev <= 0:
        return False
    # position dropped sharply -> likely liquidation (full or partial)
    if current_perp <= prev * 0.05:
        return True
    if prev - current_perp >= prev * 0.5:
        return True
    return False


def run_loop(client: HtxClient, state: StrategyState, cfg: dict, state_path) -> None:
    if state.fsm == FSM_DONE:
        logger.info("already DONE")
        return
    if state.fsm == FSM_RECONCILING:
        reconcile_until_flat(client, state, cfg, state_path)
        return

    logger.info("run loop started fsm=%s earn_qty=%.8f", state.fsm, state.earn_qty)
    if state.last_perp_qty <= 0:
        state.last_perp_qty = client.swap_short_volume(state.swap_symbol) or state.perp_qty
        state.save(state_path)

    while state.fsm not in (FSM_DONE, FSM_RECONCILING, FSM_LIQUIDATED_FAST, FSM_LIQUIDATED_FALLBACK):
        try:
            mark = client.swap_ticker(state.swap_symbol)
            liq = client.swap_liquidation_price(state.swap_symbol)
            perp = client.swap_short_volume(state.swap_symbol)
            if liq <= 0:
                logger.warning("liquidation price unavailable; pre-redeem thresholds disabled this tick")
                dist = 1.0
            else:
                dist = _dist_to_liq_pct(mark, liq, is_short=True)

            if detect_liquidation(state, perp):
                on_liquidation(client, state, cfg, state_path, pre_redeemed=state.pre_redeemed)
                break

            if perp <= 0 and state.last_perp_qty > 0:
                on_liquidation(client, state, cfg, state_path, pre_redeemed=state.pre_redeemed)
                break

            state.last_perp_qty = perp
            maybe_pre_redeem(client, state, cfg, state_path, dist)

            if state.fsm == FSM_PRE_REDEEMING and not state.pre_redeemed:
                _confirm_pre_redeemed(client, state, cfg)
                state.save(state_path)

            interval = poll_interval(cfg, dist)
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("stopped by user")
            break
        except Exception as exc:
            logger.exception("loop error: %s", exc)
            time.sleep(2.0)

    if state.fsm in (FSM_LIQUIDATED_FAST, FSM_LIQUIDATED_FALLBACK, FSM_RECONCILING):
        reconcile_until_flat(client, state, cfg, state_path)


def emergency_exit(client: HtxClient, state: StrategyState, cfg: dict, state_path) -> None:
    logger.warning("emergency exit")
    _start_redeem(client, state, cfg)
    avail = wait_trump_available(client, state, cfg, state.earn_qty)
    _sell_spot_with_retry(client, state, cfg, avail)
    _ensure_perp_flat(client, state)
    state.fsm = FSM_RECONCILING
    state.save(state_path)
    reconcile_until_flat(client, state, cfg, state_path)
