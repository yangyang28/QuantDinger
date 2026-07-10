"""Two-leg enter / exit / rebalance with multi-exchange support."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.exchange_execution import resolve_exchange_config
from app.services.hedge_arb.config import HedgeArbConfig, parse_hedge_arb_config
from app.services.hedge_arb.exchange_adapter import (
    HedgeExchangeContext,
    build_hedge_context,
    place_leg_order,
    read_live_legs,
    set_perp_leverage,
)
from app.services.hedge_arb.signals import HedgeArbSignals, collect_signals
from app.services.hedge_arb.sizing import (
    align_dual_leg_qty,
    base_qty_gap,
    estimate_unrealized_pnl,
    leg_notional_usdt,
    normalize_perp_qty,
    normalize_spot_qty,
    notional_drift_pct,
    plan_entry_quantities,
    qty_drift_metrics,
)
from app.services.hedge_arb.state import HedgeArbState, HedgeArbStateRepository, utc_now_iso
from app.services.live_trading.base import LiveOrderResult, LiveTradingError
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log

logger = get_logger(__name__)


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _hours_since(raw: Optional[str]) -> float:
    dt = _parse_ts(raw)
    if not dt:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


class HedgeArbOrchestrator:
    def __init__(
        self,
        *,
        strategy_id: int,
        user_id: int,
        exchange_config: Dict[str, Any],
        trading_config: Dict[str, Any],
    ):
        self.strategy_id = int(strategy_id)
        self.user_id = int(user_id)
        self.exchange_config = resolve_exchange_config(exchange_config or {}, user_id=self.user_id)
        self.trading_config = trading_config if isinstance(trading_config, dict) else {}
        self.config = parse_hedge_arb_config(self.trading_config)
        self.state_repo = HedgeArbStateRepository()

    def _ctx(self) -> HedgeExchangeContext:
        return build_hedge_context(
            user_id=self.user_id,
            exchange_config=self.exchange_config,
            spot_symbol=self.config.spot_symbol(),
            perp_symbol=self.config.swap_symbol(),
        )

    def get_signals(self) -> HedgeArbSignals:
        ctx = self._ctx()
        return collect_signals(
            self.config.symbol,
            exchange_id=ctx.exchange_id,
            testnet=ctx.testnet,
        )

    def _record_fill(self, state: HedgeArbState, *, leg: str, result: LiveOrderResult) -> None:
        extra = dict(state.extra or {})
        fills: List[Dict[str, Any]] = list(extra.get("recent_fills") or [])
        fills.append({
            "leg": leg,
            "filled": float(result.filled or 0.0),
            "avg_price": float(result.avg_price or 0.0),
            "order_id": str(result.exchange_order_id or ""),
            "ts": utc_now_iso(),
        })
        extra["recent_fills"] = fills[-20:]
        state.extra = extra

    def _compute_performance(
        self,
        *,
        spot_qty: float,
        perp_qty: float,
        signals: HedgeArbSignals,
        state: HedgeArbState,
    ) -> Dict[str, Any]:
        extra = state.extra if isinstance(state.extra, dict) else {}
        entry_spot = float(extra.get("entry_spot_price") or signals.spot_price or 0.0)
        entry_perp = float(extra.get("entry_perp_price") or signals.perp_mark_price or 0.0)
        unrealized = estimate_unrealized_pnl(
            spot_qty=spot_qty,
            perp_qty=perp_qty,
            spot_price=signals.spot_price,
            perp_price=signals.perp_mark_price,
            entry_spot_price=entry_spot,
            entry_perp_price=entry_perp,
        )
        spot_n = leg_notional_usdt(spot_qty, signals.spot_price)
        perp_n = leg_notional_usdt(perp_qty, signals.perp_mark_price)
        funding_est = float(state.cumulative_funding_est or 0.0)
        return {
            "spot_notional_usdt": spot_n,
            "perp_notional_usdt": perp_n,
            "unrealized_pnl_usdt": unrealized,
            "cumulative_funding_est": funding_est,
            "total_est_pnl_usdt": unrealized + funding_est,
            "entry_spot_price": entry_spot,
            "entry_perp_price": entry_perp,
        }

    def get_status(self) -> Dict[str, Any]:
        ctx = self._ctx()
        state = self.state_repo.ensure_row(self.strategy_id, self.config.symbol)
        signals = self.get_signals()

        spot_qty = 0.0
        perp_qty = 0.0
        live_error = ""
        try:
            spot_qty, perp_qty = read_live_legs(ctx)
        except Exception as e:
            live_error = str(e)
            logger.warning("hedge_arb live legs sid=%s: %s", self.strategy_id, e)
            spot_qty = float(state.spot_qty or 0.0)
            perp_qty = float(state.perp_qty or 0.0)

        if spot_qty > 0 or perp_qty > 0:
            state.spot_qty = spot_qty
            state.perp_qty = perp_qty
            if state.status == "flat":
                state.status = "holding"
            self.state_repo.upsert(state)

        drift = notional_drift_pct(
            spot_qty, signals.spot_price, perp_qty, signals.perp_mark_price,
        )
        gap, qty_drift, qty_matched = qty_drift_metrics(spot_qty, perp_qty)
        perf = self._compute_performance(
            spot_qty=spot_qty, perp_qty=perp_qty, signals=signals, state=state,
        )

        return {
            "strategy_id": self.strategy_id,
            "status": state.status if (spot_qty > 0 or perp_qty > 0) else (
                "flat" if state.status != "error" else state.status
            ),
            "symbol": self.config.symbol,
            "exchange_id": ctx.exchange_id,
            "spot_symbol": ctx.spot_symbol,
            "perp_symbol": ctx.perp_symbol,
            "spot_qty": spot_qty,
            "perp_qty": perp_qty,
            "live_data_ok": not bool(live_error),
            "live_data_error": live_error,
            "signals": {
                "funding_rate": signals.funding_rate,
                "spot_price": signals.spot_price,
                "perp_mark_price": signals.perp_mark_price,
                "basis_pct": signals.basis_pct,
                "source": signals.source,
            },
            "notional_drift_pct": drift,
            "base_qty_gap": gap,
            "qty_drift_pct": qty_drift,
            "qty_matched": qty_matched,
            "performance": perf,
            "recent_fills": (state.extra or {}).get("recent_fills") or [],
            "entry_basis_pct": state.entry_basis_pct,
            "entry_funding_rate": state.entry_funding_rate,
            "cumulative_funding_est": state.cumulative_funding_est,
            "entered_at": state.entered_at,
            "last_rebalance_at": state.last_rebalance_at,
            "last_error": state.last_error,
            "config": {
                "spot_qty": self.config.spot_qty,
                "perp_qty": self.config.perp_qty,
                "notional_usdt": self.config.notional_usdt,
                "entry_funding_rate": self.config.entry_funding_rate,
                "exit_funding_rate": self.config.exit_funding_rate,
                "rebalance_threshold_pct": self.config.rebalance_threshold_pct,
                "entry_order_mode": self.config.entry_order_mode,
                "leverage": self.config.leverage,
            },
        }

    def enter(
        self,
        *,
        spot_qty: Optional[float] = None,
        perp_qty: Optional[float] = None,
        notional_usdt: Optional[float] = None,
    ) -> Dict[str, Any]:
        ctx = self._ctx()
        state = self.state_repo.ensure_row(self.strategy_id, self.config.symbol)
        if state.status == "holding" and state.spot_qty > 0 and state.perp_qty > 0:
            return {"ok": False, "reason": "already_holding", "status": self.get_status()}

        signals = self.get_signals()
        ref_price = signals.spot_price or signals.perp_mark_price
        if ref_price <= 0:
            raise LiveTradingError("Cannot enter: missing reference price")

        if notional_usdt is not None and float(notional_usdt) > 0:
            derived = float(notional_usdt) / ref_price
            req_spot = float(spot_qty if spot_qty is not None else derived)
            req_perp = float(perp_qty if perp_qty is not None else derived)
        else:
            req_spot = float(
                spot_qty if spot_qty is not None else self.config.effective_spot_qty(ref_price)
            )
            req_perp = float(
                perp_qty if perp_qty is not None else self.config.effective_perp_qty(ref_price)
            )

        spot_order_qty, perp_order_qty, _, _ = plan_entry_quantities(
            ctx,
            spot_qty=req_spot,
            perp_qty=req_perp,
            reference_price=ref_price,
        )
        if spot_order_qty <= 0 or perp_order_qty <= 0:
            raise LiveTradingError(
                "Both spot_qty and perp_qty must be positive after exchange lot normalization"
            )
        set_perp_leverage(ctx, leverage=self.config.leverage)

        spot_result: Optional[LiveOrderResult] = None
        perp_result: Optional[LiveOrderResult] = None
        pre_spot, pre_perp = read_live_legs(ctx)

        try:
            if spot_order_qty > 0:
                spot_result = place_leg_order(
                    ctx,
                    market_type="spot",
                    side="buy",
                    quantity=spot_order_qty,
                    client_order_id=f"ha{self.strategy_id}s",
                    for_entry=True,
                    entry_order_mode=self.config.entry_order_mode,
                    pre_position_qty=pre_spot,
                    ref_price=ref_price,
                )
                if float(spot_result.filled or 0.0) <= 0:
                    raise LiveTradingError(
                        f"Spot leg filled zero (requested={spot_order_qty:g})"
                    )

            if perp_order_qty > 0:
                perp_result = place_leg_order(
                    ctx,
                    market_type="swap",
                    side="sell",
                    quantity=perp_order_qty,
                    client_order_id=f"ha{self.strategy_id}p",
                    for_entry=True,
                    entry_order_mode="market",
                    force_market=True,
                    pre_position_qty=pre_perp,
                    ref_price=ref_price,
                )
                if float(perp_result.filled or 0.0) <= 0:
                    raise LiveTradingError(
                        f"Perp leg filled zero (requested={perp_order_qty:g}); "
                        "check futures margin / position mode"
                    )

            live_spot, live_perp = read_live_legs(ctx)
            if live_spot <= 0 and live_perp <= 0:
                raise LiveTradingError("No live position after entry orders")

        except Exception as e:
            self._compensate_partial(ctx, spot_result, perp_result)
            err = str(e)
            state.status = "flat"
            state.last_error = err
            self.state_repo.upsert(state)
            append_strategy_log(self.strategy_id, "error", f"Hedge enter failed: {err}")
            raise LiveTradingError(err) from e

        extra = dict(state.extra or {})
        if spot_result and float(spot_result.avg_price or 0) > 0:
            extra["entry_spot_price"] = float(spot_result.avg_price)
        elif signals.spot_price > 0:
            extra["entry_spot_price"] = signals.spot_price
        if perp_result and float(perp_result.avg_price or 0) > 0:
            extra["entry_perp_price"] = float(perp_result.avg_price)
        elif signals.perp_mark_price > 0:
            extra["entry_perp_price"] = signals.perp_mark_price
        extra["last_funding_accrual_at"] = utc_now_iso()

        new_state = HedgeArbState(
            strategy_id=self.strategy_id,
            status="holding",
            symbol=self.config.symbol,
            spot_qty=live_spot,
            perp_qty=live_perp,
            entry_basis_pct=signals.basis_pct,
            entry_funding_rate=signals.funding_rate,
            entered_at=utc_now_iso(),
            last_error="",
            extra=extra,
        )
        if spot_result:
            self._record_fill(new_state, leg="spot", result=spot_result)
        if perp_result:
            self._record_fill(new_state, leg="perp", result=perp_result)
        self.state_repo.upsert(new_state)
        append_strategy_log(
            self.strategy_id,
            "info",
            f"Hedge entered {self.config.symbol} [{ctx.exchange_id}]: "
            f"spot={live_spot:.6f} perp_short={live_perp:.6f} "
            f"(planned spot={spot_order_qty:g} perp={perp_order_qty:g}) "
            f"funding={signals.funding_rate:.6f} basis={signals.basis_pct:.4%}",
        )
        return {"ok": True, "spot_qty": live_spot, "perp_qty": live_perp, "status": self.get_status()}

    def exit(self) -> Dict[str, Any]:
        ctx = self._ctx()
        state = self.state_repo.ensure_row(self.strategy_id, self.config.symbol)
        spot_qty, perp_qty = read_live_legs(ctx)

        if spot_qty <= 0 and perp_qty <= 0:
            flat = HedgeArbState(
                strategy_id=self.strategy_id,
                status="flat",
                symbol=self.config.symbol,
                spot_qty=0.0,
                perp_qty=0.0,
                last_error="",
            )
            self.state_repo.upsert(flat)
            return {"ok": True, "reason": "already_flat", "status": self.get_status()}

        errors: List[str] = []
        if perp_qty > 0:
            close_perp = normalize_perp_qty(ctx, perp_qty)
            try:
                place_leg_order(
                    ctx,
                    market_type="swap",
                    side="buy",
                    quantity=close_perp,
                    reduce_only=True,
                    client_order_id=f"ha{self.strategy_id}px",
                    force_market=True,
                    pre_position_qty=perp_qty,
                )
            except Exception as e:
                errors.append(f"perp_close: {e}")

        if spot_qty > 0:
            close_spot = normalize_spot_qty(ctx, spot_qty)
            try:
                place_leg_order(
                    ctx,
                    market_type="spot",
                    side="sell",
                    quantity=close_spot,
                    reduce_only=True,
                    client_order_id=f"ha{self.strategy_id}sx",
                    force_market=True,
                    pre_position_qty=spot_qty,
                )
            except Exception as e:
                errors.append(f"spot_close: {e}")

        live_spot, live_perp = read_live_legs(ctx)
        new_status = "flat" if live_spot <= 1e-12 and live_perp <= 1e-12 else "holding"
        new_state = HedgeArbState(
            strategy_id=self.strategy_id,
            status=new_status,
            symbol=self.config.symbol,
            spot_qty=live_spot,
            perp_qty=live_perp,
            last_error="; ".join(errors),
            extra=state.extra,
        )
        self.state_repo.upsert(new_state)
        if errors:
            append_strategy_log(self.strategy_id, "warning", f"Hedge exit partial: {'; '.join(errors)}")
            return {"ok": False, "errors": errors, "status": self.get_status()}
        append_strategy_log(self.strategy_id, "info", f"Hedge exited {self.config.symbol}")
        return {"ok": True, "status": self.get_status()}

    def rebalance(self) -> Dict[str, Any]:
        ctx = self._ctx()
        state = self.state_repo.ensure_row(self.strategy_id, self.config.symbol)
        signals = self.get_signals()
        spot_qty, perp_qty = read_live_legs(ctx)

        if spot_qty <= 0 and perp_qty <= 0:
            return {"ok": False, "reason": "flat", "status": self.get_status()}

        drift = notional_drift_pct(
            spot_qty, signals.spot_price, perp_qty, signals.perp_mark_price,
        )
        _, qty_drift_pct_val, _ = qty_drift_metrics(spot_qty, perp_qty)
        if (
            drift < self.config.rebalance_threshold_pct
            and qty_drift_pct_val < self.config.rebalance_threshold_pct
        ):
            return {"ok": True, "reason": "within_threshold", "drift_pct": drift, "status": self.get_status()}

        gap = base_qty_gap(spot_qty, perp_qty)
        try:
            if gap > 0:
                add_qty = align_dual_leg_qty(
                    symbol=ctx.perp_symbol,
                    quantity=abs(gap),
                    spot_client=ctx.spot_client,
                    perp_client=ctx.perp_client,
                )
                if add_qty <= 0:
                    return {"ok": False, "reason": "qty_below_step", "status": self.get_status()}
                place_leg_order(
                    ctx,
                    market_type="swap",
                    side="sell",
                    quantity=add_qty,
                    client_order_id=f"ha{self.strategy_id}rb",
                    force_market=True,
                    pre_position_qty=perp_qty,
                    ref_price=signals.perp_mark_price,
                )
            elif gap < 0:
                reduce_qty = align_dual_leg_qty(
                    symbol=ctx.perp_symbol,
                    quantity=abs(gap),
                    spot_client=ctx.spot_client,
                    perp_client=ctx.perp_client,
                )
                if reduce_qty <= 0:
                    return {"ok": False, "reason": "qty_below_step", "status": self.get_status()}
                place_leg_order(
                    ctx,
                    market_type="swap",
                    side="buy",
                    quantity=reduce_qty,
                    reduce_only=True,
                    client_order_id=f"ha{self.strategy_id}rb",
                    force_market=True,
                    pre_position_qty=perp_qty,
                    ref_price=signals.perp_mark_price,
                )
        except Exception as e:
            state.last_error = str(e)
            self.state_repo.upsert(state)
            raise LiveTradingError(str(e)) from e

        live_spot, live_perp = read_live_legs(ctx)
        state.spot_qty = live_spot
        state.perp_qty = live_perp
        state.last_rebalance_at = utc_now_iso()
        state.last_error = ""
        self.state_repo.upsert(state)
        append_strategy_log(
            self.strategy_id,
            "info",
            f"Hedge rebalanced {self.config.symbol}: drift={drift:.2%} gap={gap:.6f}",
        )
        return {"ok": True, "drift_pct": drift, "gap": gap, "status": self.get_status()}

    def accrue_funding_tick(self) -> None:
        """Update cumulative funding estimate while holding (called from runner)."""
        from app.services.hedge_arb.sizing import accrue_funding_estimate

        state = self.state_repo.get(self.strategy_id)
        if not state or state.status != "holding":
            return
        signals = self.get_signals()
        extra = dict(state.extra or {})
        last_at = extra.get("last_funding_accrual_at") or state.entered_at
        hours = _hours_since(str(last_at or ""))
        if hours <= 0:
            return
        delta = accrue_funding_estimate(
            funding_rate=signals.funding_rate,
            spot_qty=float(state.spot_qty or 0.0),
            perp_qty=float(state.perp_qty or 0.0),
            mark_price=signals.perp_mark_price or signals.spot_price,
            hours_elapsed=hours,
        )
        if delta != 0:
            state.cumulative_funding_est = float(state.cumulative_funding_est or 0.0) + delta
            extra["last_funding_accrual_at"] = utc_now_iso()
            state.extra = extra
            self.state_repo.upsert(state)

    def _compensate_partial(
        self,
        ctx: HedgeExchangeContext,
        spot_result: Optional[LiveOrderResult],
        perp_result: Optional[LiveOrderResult],
    ) -> None:
        spot_filled = float(getattr(spot_result, "filled", 0.0) or 0.0) if spot_result else 0.0
        perp_filled = float(getattr(perp_result, "filled", 0.0) or 0.0) if perp_result else 0.0
        if spot_filled > 0 and perp_filled <= 0:
            try:
                place_leg_order(
                    ctx,
                    market_type="spot",
                    side="sell",
                    quantity=spot_filled,
                    reduce_only=True,
                    client_order_id=f"ha{self.strategy_id}cp",
                    force_market=True,
                )
                append_strategy_log(
                    self.strategy_id,
                    "warning",
                    f"Compensated orphan spot leg: sold {spot_filled:.6f}",
                )
            except Exception as e:
                logger.error("hedge_arb compensate spot sid=%s: %s", self.strategy_id, e)
        if perp_filled > 0 and spot_filled <= 0:
            try:
                place_leg_order(
                    ctx,
                    market_type="swap",
                    side="buy",
                    quantity=perp_filled,
                    reduce_only=True,
                    client_order_id=f"ha{self.strategy_id}cp",
                    force_market=True,
                )
                append_strategy_log(
                    self.strategy_id,
                    "warning",
                    f"Compensated orphan perp leg: closed {perp_filled:.6f}",
                )
            except Exception as e:
                logger.error("hedge_arb compensate perp sid=%s: %s", self.strategy_id, e)
