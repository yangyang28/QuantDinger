"""HTX earn + perp short hedge orchestrator."""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from app.services.htx_earn_hedge.config import HtxEarnHedgeConfig, parse_htx_earn_hedge_config
from app.services.htx_earn_hedge.state import (
    FSM_ARMED,
    FSM_DONE,
    FSM_IDLE,
    FSM_PRE_REDEEMED,
    FSM_PRE_REDEEMING,
    FSM_RECONCILING,
    HtxEarnHedgeState,
    HtxEarnHedgeStateRepository,
)
from app.services.live_trading.base import LiveTradingError
from app.services.live_trading.factory import create_client
from app.services.live_trading.htx import HtxClient
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log

logger = get_logger(__name__)
UTC8 = timezone(timedelta(hours=8))


def _new_request_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _dist_to_liq_pct(mark: float, liq: float) -> float:
    if mark <= 0 or liq <= 0:
        return 1.0
    return (liq - mark) / liq


class HtxEarnHedgeOrchestrator:
    def __init__(
        self,
        *,
        strategy_id: int,
        user_id: int,
        exchange_config: Dict[str, Any],
        trading_config: Dict[str, Any],
    ):
        self.strategy_id = int(strategy_id)
        self.user_id = int(user_id or 1)
        self.exchange_config = exchange_config if isinstance(exchange_config, dict) else {}
        self.trading_config = trading_config if isinstance(trading_config, dict) else {}
        self.cfg = parse_htx_earn_hedge_config(self.trading_config)
        self.repo = HtxEarnHedgeStateRepository()

    def _require_htx(self) -> None:
        ex = str(self.exchange_config.get("exchange_id") or "").strip().lower()
        if ex not in ("htx", "huobi"):
            raise LiveTradingError("htx_earn_hedge requires HTX exchange credentials")

    def _spot_client(self) -> HtxClient:
        self._require_htx()
        client = create_client(self.exchange_config, market_type="spot")
        if not isinstance(client, HtxClient):
            raise LiveTradingError("HTX spot client required")
        return client

    def _swap_client(self) -> HtxClient:
        self._require_htx()
        client = create_client(self.exchange_config, market_type="swap")
        if not isinstance(client, HtxClient):
            raise LiveTradingError("HTX swap client required")
        return client

    def deploy(self) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id, self.cfg.symbol)
        if state.fsm not in (FSM_IDLE, FSM_DONE) and state.deployed_at:
            raise LiveTradingError(f"already deployed (fsm={state.fsm})")

        spot = self._spot_client()
        swap = self._swap_client()
        sym = self.cfg.symbol
        ccy = self.cfg.currency

        tick = spot.get_ticker(symbol=sym)
        last = float(tick.get("close") or tick.get("price") or 0)
        if last <= 0:
            raise LiveTradingError("cannot fetch spot price")

        base_qty = self.cfg.spot_usdt / last if last > 0 else 0.0
        spot.place_market_order(
            symbol=sym,
            side="buy",
            qty=base_qty,
            client_order_id=_new_request_id("buy"),
        )
        time.sleep(1.5)
        avail = spot.get_spot_trade_balance(ccy)
        if avail <= 0:
            avail = spot.get_spot_trade_balance(ccy)
        if avail <= 0:
            raise LiveTradingError(f"no {ccy} after spot buy")

        project = spot.earn_find_flexible_project(ccy)
        project_id = int(project.get("id") or project.get("projectId") or 0)
        if project_id <= 0:
            raise LiveTradingError("earn project id not found")
        amt = f"{avail:.8f}".rstrip("0").rstrip(".")
        spot.earn_subscribe(project_id=project_id, amount=amt, request_id=_new_request_id("sub"))
        time.sleep(1.0)

        earn_total, order_id = spot.earn_total_qty(ccy)
        if order_id is None:
            assets = spot.earn_user_assets(ccy)
            if assets:
                order_id = int(assets[0].get("orderId") or 0) or None

        perp_qty = self.cfg.perp_notional_usdt / last if last > 0 else 0.0
        swap.set_leverage(symbol=sym, leverage=float(self.cfg.leverage))
        swap.place_market_order(
            symbol=sym,
            side="sell",
            qty=perp_qty,
            client_order_id=_new_request_id("short"),
        )
        perp_open = swap.swap_short_base_qty(symbol=sym) or perp_qty

        state.fsm = FSM_ARMED
        state.symbol = self.cfg.symbol
        state.currency = ccy
        state.earn_order_id = order_id
        state.earn_qty = earn_total or avail
        state.perp_qty = perp_open
        state.last_perp_qty = perp_open
        state.pre_redeemed = False
        state.redeem_sent = False
        state.redeem_request_id = ""
        state.deployed_at = datetime.now(timezone.utc).isoformat()
        state.last_error = ""
        self.repo.save(state)
        append_strategy_log(self.strategy_id, "info", f"HTX earn hedge deployed earn={state.earn_qty:.8f} perp={state.perp_qty:.8f}")
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id, self.cfg.symbol)
        spot_avail = earn_qty = perp_qty = mark = liq = 0.0
        dist_pct = None
        try:
            spot = self._spot_client()
            swap = self._swap_client()
            ccy = state.currency or self.cfg.currency
            spot_avail = spot.get_spot_trade_balance(ccy)
            earn_qty, _ = spot.earn_total_qty(ccy)
            perp_qty = swap.swap_short_base_qty(symbol=self.cfg.symbol)
            mark = float(swap.get_ticker(symbol=self.cfg.symbol).get("close") or 0)
            liq = swap.swap_liquidation_price(symbol=self.cfg.symbol)
            if liq > 0 and mark > 0:
                dist_pct = _dist_to_liq_pct(mark, liq)
        except Exception as exc:
            state.last_error = str(exc)
            self.repo.save(state)
        return {
            "fsm": state.fsm,
            "pre_redeemed": state.pre_redeemed,
            "deployed_at": state.deployed_at,
            "earn_order_id": state.earn_order_id,
            "earn_qty": earn_qty or state.earn_qty,
            "spot_avail": spot_avail,
            "perp_qty": perp_qty or state.perp_qty,
            "mark": mark,
            "liq_price": liq,
            "dist_to_liq_pct": dist_pct,
            "last_error": state.last_error,
            "config": {
                "spot_usdt": self.cfg.spot_usdt,
                "perp_notional_usdt": self.cfg.perp_notional_usdt,
                "leverage": self.cfg.leverage,
                "pre_redeem_pct": self.cfg.pre_redeem_pct,
            },
        }

    def _in_maintenance_hour(self) -> bool:
        return datetime.now(UTC8).hour in (0,)

    def _wait_spot_available(self, spot: HtxClient, target: float) -> float:
        deadline = time.time() + 1.2
        need = max(target * 0.99, self.cfg.min_sell_qty)
        while time.time() < deadline:
            avail = spot.get_spot_trade_balance(self.cfg.currency)
            if avail >= need:
                return avail
            time.sleep(0.08)
        return spot.get_spot_trade_balance(self.cfg.currency)

    def _start_redeem(self, spot: HtxClient, state: HtxEarnHedgeState) -> bool:
        if state.redeem_sent:
            return True
        earn, order_id = spot.earn_total_qty(self.cfg.currency)
        oid = order_id or state.earn_order_id
        if not oid:
            assets = spot.earn_user_assets(self.cfg.currency)
            if assets:
                oid = int(assets[0].get("orderId") or 0) or None
        if not oid:
            return False
        qty = earn if earn > 0 else state.earn_qty
        if qty <= 0:
            return False
        if not state.redeem_request_id:
            state.redeem_request_id = _new_request_id("redeem")
        spot.earn_redeem(order_id=int(oid), amount=f"{qty:.8f}".rstrip("0").rstrip("."), request_id=state.redeem_request_id)
        state.redeem_sent = True
        state.earn_qty = qty
        state.earn_order_id = int(oid)
        self.repo.save(state)
        return True

    def _sell_spot(self, spot: HtxClient, qty: float) -> None:
        if qty < self.cfg.min_sell_qty:
            return
        spot.place_market_order(
            symbol=self.cfg.symbol,
            side="sell",
            qty=qty,
            client_order_id=_new_request_id("sell"),
        )

    def _ensure_perp_flat(self, swap: HtxClient) -> None:
        perp = swap.swap_short_base_qty(symbol=self.cfg.symbol)
        if perp <= self.cfg.min_sell_qty:
            return
        swap.place_market_order(
            symbol=self.cfg.symbol,
            side="buy",
            qty=perp,
            reduce_only=True,
            client_order_id=_new_request_id("close"),
        )

    def _on_liquidation(self, state: HtxEarnHedgeState) -> None:
        spot = self._spot_client()
        swap = self._swap_client()
        path = "fast" if state.pre_redeemed else "fallback"
        append_strategy_log(self.strategy_id, "warning", f"HTX earn hedge liquidation path={path}")
        if state.pre_redeemed:
            avail = spot.get_spot_trade_balance(self.cfg.currency)
            self._sell_spot(spot, avail)
            self._ensure_perp_flat(swap)
        else:
            self._start_redeem(spot, state)
            self._ensure_perp_flat(swap)
            avail = self._wait_spot_available(spot, state.earn_qty)
            self._sell_spot(spot, avail)
        state.fsm = FSM_RECONCILING
        self.repo.save(state)
        self._reconcile_once(state)

    def _reconcile_once(self, state: HtxEarnHedgeState) -> None:
        spot = self._spot_client()
        swap = self._swap_client()
        ccy = self.cfg.currency
        earn, oid = spot.earn_total_qty(ccy)
        if earn >= self.cfg.min_sell_qty and oid:
            try:
                spot.earn_redeem(
                    order_id=int(oid),
                    amount=f"{earn:.8f}".rstrip("0").rstrip("."),
                    request_id=_new_request_id("redeem-rec"),
                )
            except Exception as exc:
                logger.warning("htx_earn_hedge reconcile redeem: %s", exc)
        avail = spot.get_spot_trade_balance(ccy)
        if avail >= self.cfg.min_sell_qty:
            try:
                self._sell_spot(spot, avail)
            except Exception as exc:
                logger.warning("htx_earn_hedge reconcile sell: %s", exc)
        perp = swap.swap_short_base_qty(symbol=self.cfg.symbol)
        if perp >= self.cfg.min_sell_qty:
            try:
                self._ensure_perp_flat(swap)
            except Exception as exc:
                logger.warning("htx_earn_hedge reconcile close: %s", exc)
        earn2, _ = spot.earn_total_qty(ccy)
        spot2 = spot.get_spot_trade_balance(ccy)
        perp2 = swap.swap_short_base_qty(symbol=self.cfg.symbol)
        if earn2 < self.cfg.min_sell_qty and spot2 < self.cfg.min_sell_qty and perp2 < self.cfg.min_sell_qty:
            state.fsm = FSM_DONE
            self.repo.save(state)
            append_strategy_log(self.strategy_id, "info", "HTX earn hedge flat DONE")

    def emergency_exit(self) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id, self.cfg.symbol)
        spot = self._spot_client()
        swap = self._swap_client()
        self._start_redeem(spot, state)
        avail = self._wait_spot_available(spot, state.earn_qty)
        self._sell_spot(spot, avail)
        self._ensure_perp_flat(swap)
        state.fsm = FSM_RECONCILING
        self.repo.save(state)
        self._reconcile_once(state)
        append_strategy_log(self.strategy_id, "warning", "HTX earn hedge emergency exit")
        return self.get_status()

    def tick(self) -> None:
        state = self.repo.ensure_row(self.strategy_id, self.cfg.symbol)
        if state.fsm in (FSM_IDLE, FSM_DONE):
            return
        if state.fsm == FSM_RECONCILING:
            self._reconcile_once(state)
            return

        spot = self._spot_client()
        swap = self._swap_client()
        mark = float(swap.get_ticker(symbol=self.cfg.symbol).get("close") or 0)
        liq = swap.swap_liquidation_price(symbol=self.cfg.symbol)
        perp = swap.swap_short_base_qty(symbol=self.cfg.symbol)

        prev = float(state.last_perp_qty or state.perp_qty or 0)
        liquidated = prev > 0 and (perp <= prev * 0.05 or (prev - perp) >= prev * 0.5)
        if liquidated or (perp <= 0 and prev > 0):
            self._on_liquidation(state)
            return

        dist = _dist_to_liq_pct(mark, liq) if liq > 0 else 1.0
        trigger = self.cfg.pre_redeem_pct
        if self._in_maintenance_hour():
            trigger = max(trigger, self.cfg.maintenance_pre_redeem_pct)
        if not state.pre_redeemed and dist <= self.cfg.emergency_redeem_pct:
            trigger = min(trigger, self.cfg.emergency_redeem_pct)

        if (
            not state.pre_redeemed
            and state.fsm in (FSM_ARMED, FSM_PRE_REDEEMING)
            and liq > 0
            and dist <= trigger
        ):
            state.fsm = FSM_PRE_REDEEMING
            self.repo.save(state)
            if self._start_redeem(spot, state):
                avail = self._wait_spot_available(spot, state.earn_qty)
                if avail >= max(state.earn_qty * 0.99, self.cfg.min_sell_qty):
                    state.pre_redeemed = True
                    state.fsm = FSM_PRE_REDEEMED
                    self.repo.save(state)
                    append_strategy_log(
                        self.strategy_id,
                        "info",
                        f"HTX earn pre-redeemed dist={dist:.4%} avail={avail:.8f}",
                    )

        state.last_perp_qty = perp
        self.repo.save(state)
