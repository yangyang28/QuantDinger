"""Binance spot long + USDT-M perp short 1:1 orchestrator."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict

from app.services.binance_btc_arb.config import BinanceBtcArbConfig, parse_binance_btc_arb_config
from app.services.binance_btc_arb.sizing import alignment_metrics, plan_1to1_deploy
from app.services.binance_btc_arb.state import (
    FSM_ARMED,
    FSM_DONE,
    FSM_IDLE,
    FSM_PRE_EXIT,
    FSM_RECONCILING,
    BinanceBtcArbState,
    BinanceBtcArbStateRepository,
)
from app.services.live_trading.base import LiveTradingError
from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.factory import create_client
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log

logger = get_logger(__name__)


def _new_request_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _dist_to_liq_pct(mark: float, liq: float) -> float:
    if mark <= 0 or liq <= 0:
        return 1.0
    return (liq - mark) / liq


def _deploy_step_error(step: str, exc: Exception) -> LiveTradingError:
    return LiveTradingError(f"deploy step {step} failed: {exc}")


class BinanceBtcArbOrchestrator:
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
        self.cfg = parse_binance_btc_arb_config(self.trading_config)
        self.repo = BinanceBtcArbStateRepository()

    def _require_binance(self) -> None:
        ex = str(self.exchange_config.get("exchange_id") or "").strip().lower()
        if ex != "binance":
            raise LiveTradingError("binance_btc_arb requires exchange_id=binance")

    def _spot_client(self) -> BinanceSpotClient:
        self._require_binance()
        client = create_client(self.exchange_config, market_type="spot")
        if not isinstance(client, BinanceSpotClient):
            raise LiveTradingError("Binance spot client required")
        return client

    def _swap_client(self) -> BinanceFuturesClient:
        self._require_binance()
        client = create_client(self.exchange_config, market_type="swap")
        if not isinstance(client, BinanceFuturesClient):
            raise LiveTradingError("Binance USDT-M futures client required")
        return client

    def _save_deploy_progress(self, state: BinanceBtcArbState, *, step: str, last_error: str = "") -> None:
        state.extra = state.extra or {}
        state.extra["deploy_step"] = step
        state.last_error = last_error
        self.repo.save(state)

    def deploy(self) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id, self.cfg.symbol)
        if state.fsm == FSM_ARMED and state.deployed_at:
            raise LiveTradingError(f"already deployed (fsm={state.fsm})")
        if state.fsm not in (FSM_IDLE, FSM_DONE, FSM_ARMED):
            raise LiveTradingError(f"cannot deploy while fsm={state.fsm}")

        spot = self._spot_client()
        swap = self._swap_client()
        sym = self.cfg.symbol
        ccy = self.cfg.currency
        min_qty = self.cfg.min_sell_qty

        tick = spot.get_ticker(symbol=sym)
        last = float(tick.get("close") or tick.get("price") or 0)
        if last <= 0:
            raise LiveTradingError("deploy step price: cannot fetch spot price")

        plan = plan_1to1_deploy(
            spot_usdt=self.cfg.spot_usdt,
            perp_notional_usdt=self.cfg.perp_notional_usdt,
            price=last,
            spot_fee_rate=self.cfg.spot_fee_rate,
            perp_fee_rate=self.cfg.perp_fee_rate,
        )
        if self.cfg.align_1to1:
            expected_spot = float(plan["target_base_qty"] or 0.0)
            expected_perp = float(plan["perp_short_qty"] or 0.0)
            spot_buy_usdt = float(plan["spot_buy_usdt"] or 0.0)
        else:
            expected_spot = self.cfg.spot_usdt / last if last > 0 else 0.0
            expected_perp = self.cfg.perp_notional_usdt / last if last > 0 else 0.0
            spot_buy_usdt = self.cfg.spot_usdt

        spot_avail = spot.get_spot_trade_balance(ccy)
        perp_open = swap.swap_short_base_qty(symbol=sym)
        usdt_avail = spot.get_spot_usdt_trade_balance()
        if usdt_avail + 1e-6 < spot_buy_usdt and spot_avail < min_qty:
            raise LiveTradingError(
                f"deploy step spot_buy: insufficient USDT (need≈{spot_buy_usdt:.2f}, "
                f"spot_usdt_avail={usdt_avail:.2f})"
            )

        fees = {
            "spot_fee_est_usdt": float(plan.get("spot_fee_est_usdt") or 0.0),
            "perp_fee_est_usdt": float(plan.get("perp_fee_est_usdt") or 0.0),
            "total_fee_est_usdt": float(plan.get("total_fee_est_usdt") or 0.0),
            "spot_fee_rate": self.cfg.spot_fee_rate,
            "perp_fee_rate": self.cfg.perp_fee_rate,
            "spot_bought_usdt": 0.0,
            "perp_opened_qty": 0.0,
        }

        need_spot_buy = spot_avail < max(expected_spot * 0.9, min_qty)
        if need_spot_buy:
            self._save_deploy_progress(state, step="spot_buy")
            try:
                spot.spot_market_buy_usdt(
                    symbol=sym,
                    usdt_amount=spot_buy_usdt,
                    client_order_id=_new_request_id("buy"),
                )
            except LiveTradingError as exc:
                raise _deploy_step_error("spot_buy", exc) from exc
            time.sleep(0.5)
            spot_avail = self._wait_spot_available(spot, max(expected_spot * 0.95, min_qty))
            if spot_avail < min_qty:
                raise LiveTradingError(
                    f"deploy step spot_buy: no {ccy} credited after buy (avail={spot_avail:.8f})"
                )
            fees["spot_bought_usdt"] = spot_buy_usdt
            gross_base = spot_buy_usdt / last if last > 0 else 0.0
            if gross_base > spot_avail > 0:
                fees["spot_fee_est_usdt"] = round((gross_base - spot_avail) * last, 4)
            state.extra = state.extra or {}
            state.extra["spot_bought_usdt"] = spot_buy_usdt
            self._save_deploy_progress(state, step="spot_buy_done")

        align_base = spot_avail
        if self.cfg.align_1to1:
            cap_base = float(plan["perp_short_qty"] or 0.0) or expected_perp
            short_target = min(align_base, cap_base) if cap_base > 0 else align_base
        else:
            short_target = expected_perp

        perp_open = swap.swap_short_base_qty(symbol=sym)
        need_perp = perp_open < max(short_target * 0.9, min_qty)
        if need_perp:
            self._save_deploy_progress(state, step="perp_short")
            try:
                swap.set_leverage(symbol=sym, leverage=float(self.cfg.leverage))
                short_qty = short_target if perp_open < min_qty else max(short_target - perp_open, 0.0)
                if short_qty >= min_qty:
                    swap.place_market_order(
                        symbol=sym,
                        side="sell",
                        quantity=short_qty,
                        client_order_id=_new_request_id("short"),
                    )
                    fees["perp_opened_qty"] = short_qty
                    fees["perp_fee_est_usdt"] = round(short_qty * last * self.cfg.perp_fee_rate, 4)
            except LiveTradingError as exc:
                raise _deploy_step_error("perp_short", exc) from exc
            perp_open = swap.swap_short_base_qty(symbol=sym) or short_target
            if perp_open < min_qty:
                raise LiveTradingError(
                    f"deploy step perp_short: no short position after order (qty={perp_open:.8f})"
                )
            self._save_deploy_progress(state, step="perp_short_done")

        spot_avail = spot.get_spot_trade_balance(ccy)
        fees["total_fee_est_usdt"] = round(
            float(fees.get("spot_fee_est_usdt") or 0.0) + float(fees.get("perp_fee_est_usdt") or 0.0),
            4,
        )
        align = alignment_metrics(spot_or_earn_qty=spot_avail, perp_qty=perp_open, price=last)

        state.fsm = FSM_ARMED
        state.symbol = self.cfg.symbol
        state.spot_qty = spot_avail
        state.perp_qty = perp_open
        state.last_perp_qty = perp_open
        state.pre_exit_done = False
        state.deployed_at = datetime.now(timezone.utc).isoformat()
        state.extra = state.extra or {}
        state.extra["deploy_step"] = "done"
        state.extra["deploy_plan"] = plan
        state.extra["fees"] = fees
        state.extra["alignment"] = align
        state.last_error = ""
        self.repo.save(state)
        append_strategy_log(
            self.strategy_id,
            "info",
            (
                f"Binance BTC arb deployed spot={state.spot_qty:.8f} perp={state.perp_qty:.8f} "
                f"matched={align.get('qty_matched')} fees≈{fees.get('total_fee_est_usdt')}U"
            ),
        )
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id, self.cfg.symbol)
        spot_qty = perp_qty = mark = liq = 0.0
        dist_pct = None
        try:
            spot = self._spot_client()
            swap = self._swap_client()
            ccy = self.cfg.currency
            spot_qty = spot.get_spot_trade_balance(ccy)
            perp_qty = swap.swap_short_base_qty(symbol=self.cfg.symbol)
            mark = float(swap.get_mark_price(symbol=self.cfg.symbol) or 0)
            if mark <= 0:
                mark = float(spot.get_ticker(symbol=self.cfg.symbol).get("close") or 0)
            liq = swap.swap_liquidation_price(symbol=self.cfg.symbol)
            if liq > 0 and mark > 0:
                dist_pct = _dist_to_liq_pct(mark, liq)
        except Exception as exc:
            msg = str(exc)
            state.last_error = msg
            self.repo.save(state)
            extra = state.extra if isinstance(state.extra, dict) else {}
            return {
                "fsm": state.fsm,
                "pre_exit_done": state.pre_exit_done,
                "deployed_at": state.deployed_at,
                "spot_qty": state.spot_qty,
                "perp_qty": state.perp_qty,
                "mark": 0.0,
                "liq_price": 0.0,
                "dist_to_liq_pct": None,
                "last_error": state.last_error,
                "deploy_step": extra.get("deploy_step"),
                "fees": extra.get("fees") or {},
                "alignment": extra.get("alignment") or {},
                "config": self._status_config(),
            }

        spot_out = spot_qty or state.spot_qty
        perp_out = perp_qty or state.perp_qty
        align = alignment_metrics(spot_or_earn_qty=spot_out, perp_qty=perp_out, price=mark)
        extra = state.extra if isinstance(state.extra, dict) else {}
        return {
            "fsm": state.fsm,
            "pre_exit_done": state.pre_exit_done,
            "deployed_at": state.deployed_at,
            "spot_qty": spot_out,
            "perp_qty": perp_out,
            "mark": mark,
            "liq_price": liq,
            "dist_to_liq_pct": dist_pct,
            "last_error": state.last_error,
            "deploy_step": extra.get("deploy_step"),
            "fees": dict(extra.get("fees") or {}),
            "alignment": align,
            "config": self._status_config(),
        }

    def _status_config(self) -> Dict[str, Any]:
        margin = (
            self.cfg.perp_notional_usdt / float(self.cfg.leverage)
            if self.cfg.leverage > 0
            else self.cfg.perp_notional_usdt
        )
        return {
            "symbol": self.cfg.symbol,
            "spot_usdt": self.cfg.spot_usdt,
            "perp_notional_usdt": self.cfg.perp_notional_usdt,
            "perp_margin_usdt": round(margin, 4),
            "leverage": self.cfg.leverage,
            "pre_exit_pct": self.cfg.pre_exit_pct,
            "align_1to1": self.cfg.align_1to1,
            "spot_fee_rate": self.cfg.spot_fee_rate,
            "perp_fee_rate": self.cfg.perp_fee_rate,
            "tick_interval_sec": self.cfg.tick_interval_sec,
        }

    def _wait_spot_available(self, spot: BinanceSpotClient, target: float, *, timeout_sec: float = 5.0) -> float:
        deadline = time.time() + timeout_sec
        need = max(target * 0.99, self.cfg.min_sell_qty)
        while time.time() < deadline:
            avail = spot.get_spot_trade_balance(self.cfg.currency)
            if avail >= need:
                return avail
            time.sleep(0.45)
        return spot.get_spot_trade_balance(self.cfg.currency)

    def _sell_spot(self, spot: BinanceSpotClient, qty: float) -> None:
        if qty < self.cfg.min_sell_qty:
            return
        spot.place_market_order(
            symbol=self.cfg.symbol,
            side="sell",
            quantity=qty,
            client_order_id=_new_request_id("sell"),
        )

    def _ensure_perp_flat(self, swap: BinanceFuturesClient) -> None:
        perp = swap.swap_short_base_qty(symbol=self.cfg.symbol)
        if perp <= self.cfg.min_sell_qty:
            return
        swap.place_market_order(
            symbol=self.cfg.symbol,
            side="buy",
            quantity=perp,
            reduce_only=True,
            client_order_id=_new_request_id("close"),
        )

    def _on_liquidation(self, state: BinanceBtcArbState) -> None:
        spot = self._spot_client()
        swap = self._swap_client()
        path = "pre_exit" if state.pre_exit_done else "full"
        append_strategy_log(self.strategy_id, "warning", f"Binance BTC arb liquidation path={path}")
        if not state.pre_exit_done:
            avail = spot.get_spot_trade_balance(self.cfg.currency)
            self._sell_spot(spot, avail)
        self._ensure_perp_flat(swap)
        state.fsm = FSM_RECONCILING
        self.repo.save(state)
        self._reconcile_once(state)

    def _reconcile_once(self, state: BinanceBtcArbState) -> None:
        spot = self._spot_client()
        swap = self._swap_client()
        ccy = self.cfg.currency
        avail = spot.get_spot_trade_balance(ccy)
        if avail >= self.cfg.min_sell_qty:
            try:
                self._sell_spot(spot, avail)
            except Exception as exc:
                logger.warning("binance_btc_arb reconcile sell: %s", exc)
        perp = swap.swap_short_base_qty(symbol=self.cfg.symbol)
        if perp >= self.cfg.min_sell_qty:
            try:
                self._ensure_perp_flat(swap)
            except Exception as exc:
                logger.warning("binance_btc_arb reconcile close: %s", exc)
        spot2 = spot.get_spot_trade_balance(ccy)
        perp2 = swap.swap_short_base_qty(symbol=self.cfg.symbol)
        if spot2 < self.cfg.min_sell_qty and perp2 < self.cfg.min_sell_qty:
            state.fsm = FSM_DONE
            state.spot_qty = 0.0
            state.perp_qty = 0.0
            self.repo.save(state)
            append_strategy_log(self.strategy_id, "info", "Binance BTC arb flat DONE")

    def emergency_exit(self) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id, self.cfg.symbol)
        spot = self._spot_client()
        swap = self._swap_client()
        avail = spot.get_spot_trade_balance(self.cfg.currency)
        self._sell_spot(spot, avail)
        self._ensure_perp_flat(swap)
        state.fsm = FSM_RECONCILING
        state.pre_exit_done = True
        self.repo.save(state)
        self._reconcile_once(state)
        append_strategy_log(self.strategy_id, "warning", "Binance BTC arb emergency exit")
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
        mark = float(swap.get_mark_price(symbol=self.cfg.symbol) or 0)
        liq = swap.swap_liquidation_price(symbol=self.cfg.symbol)
        perp = swap.swap_short_base_qty(symbol=self.cfg.symbol)

        prev = float(state.last_perp_qty or state.perp_qty or 0)
        liquidated = prev > 0 and (perp <= prev * 0.05 or (prev - perp) >= prev * 0.5)
        if liquidated or (perp <= 0 and prev > 0):
            self._on_liquidation(state)
            return

        dist = _dist_to_liq_pct(mark, liq) if liq > 0 and mark > 0 else 1.0
        if (
            not state.pre_exit_done
            and state.fsm in (FSM_ARMED, FSM_PRE_EXIT)
            and liq > 0
            and dist <= self.cfg.pre_exit_pct
        ):
            avail = spot.get_spot_trade_balance(self.cfg.currency)
            if avail >= self.cfg.min_sell_qty:
                try:
                    self._sell_spot(spot, avail)
                    state.pre_exit_done = True
                    state.fsm = FSM_PRE_EXIT
                    state.spot_qty = 0.0
                    self.repo.save(state)
                    append_strategy_log(
                        self.strategy_id,
                        "info",
                        f"Binance BTC arb pre-exit spot sold dist={dist:.4%}",
                    )
                except Exception as exc:
                    logger.warning("binance_btc_arb pre-exit sell sid=%s: %s", self.strategy_id, exc)

        state.last_perp_qty = perp
        state.perp_qty = perp
        if not state.pre_exit_done:
            state.spot_qty = spot.get_spot_trade_balance(self.cfg.currency)
        self.repo.save(state)
