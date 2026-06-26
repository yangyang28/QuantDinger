"""Two-leg enter / exit / rebalance with compensation on partial failure."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.exchange_execution import resolve_exchange_config
from app.services.hedge_arb.config import HedgeArbConfig, parse_hedge_arb_config
from app.services.hedge_arb.positions import read_live_legs, spot_base_balance
from app.services.hedge_arb.signals import HedgeArbSignals, collect_signals
from app.services.hedge_arb.sizing import (
    align_dual_leg_qty,
    base_qty_gap,
    notional_drift_pct,
    plan_entry_base_qty,
    qty_drift_metrics,
    validate_spot_buy_balance,
)
from app.services.hedge_arb.state import HedgeArbState, HedgeArbStateRepository, utc_now_iso
from app.services.live_trading.base import LiveTradingError
from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.factory import create_client, exchange_demo_mode_enabled
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log

logger = get_logger(__name__)


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
        self._testnet = exchange_demo_mode_enabled(self.exchange_config)

    def _spot_client(self) -> BinanceSpotClient:
        client = create_client(self.exchange_config, market_type="spot")
        if not isinstance(client, BinanceSpotClient):
            raise LiveTradingError("hedge_arb requires Binance spot client")
        return client

    def _perp_client(self) -> BinanceFuturesClient:
        client = create_client(self.exchange_config, market_type="swap")
        if not isinstance(client, BinanceFuturesClient):
            raise LiveTradingError("hedge_arb requires Binance USDT-M futures client")
        return client

    def _symbol(self) -> str:
        return self.config.symbol or self.config.spot_symbol()

    def _place_order(
        self,
        client: Any,
        *,
        symbol: str,
        side: str,
        quantity: float = 0.0,
        quote_order_qty: float = 0.0,
        reduce_only: bool = False,
        position_side: Optional[str] = None,
        client_order_id: Optional[str] = None,
        for_entry: bool = False,
    ) -> Any:
        """Route to best-price (默认) or plain market based on hedge config."""
        use_best = for_entry and self.config.entry_order_mode != "market"
        if use_best and getattr(type(client), "place_best_price_order", None) is not None:
            method = client.place_best_price_order
        else:
            method = client.place_market_order
        kwargs: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "client_order_id": client_order_id,
        }
        if quote_order_qty > 0:
            kwargs["quote_order_qty"] = quote_order_qty
        else:
            kwargs["quantity"] = quantity
        if position_side:
            kwargs["position_side"] = position_side
        if reduce_only:
            kwargs["reduce_only"] = reduce_only
        return method(**kwargs)

    def _sync_matched_base_qty(
        self,
        spot_client: BinanceSpotClient,
        perp_client: BinanceFuturesClient,
        symbol: str,
        *,
        context: str = "sync",
    ) -> tuple[float, float]:
        """
        Align spot long and perp short to the same base quantity.
        Prefer adjusting the perp leg; trim excess spot when needed.
        """
        spot_qty, perp_qty = read_live_legs(spot_client, perp_client, symbol)
        gap = base_qty_gap(spot_qty, perp_qty)
        if abs(gap) <= 1e-12:
            return spot_qty, perp_qty

        if gap > 0:
            add_qty = align_dual_leg_qty(
                symbol=symbol,
                quantity=gap,
                spot_client=spot_client,
                perp_client=perp_client,
            )
            if add_qty > 0:
                self._place_order(
                    perp_client,
                    symbol=symbol,
                    side="SELL",
                    quantity=add_qty,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}{context[:2]}p",
                )
        else:
            reduce_qty = align_dual_leg_qty(
                symbol=symbol,
                quantity=abs(gap),
                spot_client=spot_client,
                perp_client=perp_client,
            )
            if reduce_qty > 0:
                self._place_order(
                    perp_client,
                    symbol=symbol,
                    side="BUY",
                    quantity=reduce_qty,
                    reduce_only=True,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}{context[:2]}p",
                )

        spot_qty, perp_qty = read_live_legs(spot_client, perp_client, symbol)
        gap = base_qty_gap(spot_qty, perp_qty)
        if gap > 1e-12:
            trim = align_dual_leg_qty(
                symbol=symbol,
                quantity=gap,
                spot_client=spot_client,
                perp_client=perp_client,
            )
            if trim > 0:
                free_base = spot_base_balance(spot_client, symbol)
                sell_qty = align_dual_leg_qty(
                    symbol=symbol,
                    quantity=min(trim, free_base),
                    spot_client=spot_client,
                    perp_client=perp_client,
                )
                if sell_qty > 0:
                    spot_client.place_market_order(
                        symbol=symbol,
                        side="SELL",
                        quantity=sell_qty,
                        client_order_id=f"ha{self.strategy_id}{context[:2]}t",
                    )

        return read_live_legs(spot_client, perp_client, symbol)

    def get_signals(self) -> HedgeArbSignals:
        return collect_signals(self._symbol(), testnet=self._testnet)

    def get_status(self) -> Dict[str, Any]:
        state = self.state_repo.ensure_row(self.strategy_id, self._symbol())
        signals = self.get_signals()
        spot_qty = state.spot_qty
        perp_qty = state.perp_qty
        try:
            spot_client = self._spot_client()
            perp_client = self._perp_client()
            live_spot, live_perp = read_live_legs(spot_client, perp_client, self._symbol())
            if live_spot > 0 or live_perp > 0:
                spot_qty, perp_qty = live_spot, live_perp
        except Exception as e:
            logger.debug("hedge_arb live leg read sid=%s: %s", self.strategy_id, e)

        drift = notional_drift_pct(
            spot_qty, signals.spot_price, perp_qty, signals.perp_mark_price,
        )
        gap, qty_drift, qty_matched = qty_drift_metrics(spot_qty, perp_qty)
        return {
            "strategy_id": self.strategy_id,
            "status": state.status,
            "symbol": self._symbol(),
            "spot_qty": spot_qty,
            "perp_qty": perp_qty,
            "signals": {
                "funding_rate": signals.funding_rate,
                "spot_price": signals.spot_price,
                "perp_mark_price": signals.perp_mark_price,
                "basis_pct": signals.basis_pct,
            },
            "notional_drift_pct": drift,
            "base_qty_gap": gap,
            "qty_drift_pct": qty_drift,
            "qty_matched": qty_matched,
            "entry_basis_pct": state.entry_basis_pct,
            "entry_funding_rate": state.entry_funding_rate,
            "cumulative_funding_est": state.cumulative_funding_est,
            "entered_at": state.entered_at,
            "last_rebalance_at": state.last_rebalance_at,
            "last_error": state.last_error,
            "config": {
                "notional_usdt": self.config.notional_usdt,
                "entry_funding_rate": self.config.entry_funding_rate,
                "exit_funding_rate": self.config.exit_funding_rate,
                "rebalance_threshold_pct": self.config.rebalance_threshold_pct,
            },
        }

    def enter(self, *, notional_usdt: Optional[float] = None) -> Dict[str, Any]:
        symbol = self._symbol()
        state = self.state_repo.ensure_row(self.strategy_id, symbol)
        if state.status == "holding" and state.spot_qty > 0 and state.perp_qty > 0:
            return {"ok": False, "reason": "already_holding", "status": self.get_status()}

        signals = self.get_signals()
        notional = float(notional_usdt if notional_usdt is not None else self.config.notional_usdt)
        if notional <= 0:
            raise LiveTradingError("notional_usdt must be positive")

        spot_client = self._spot_client()
        perp_client = self._perp_client()

        ref_price = signals.spot_price or signals.perp_mark_price
        if ref_price <= 0:
            raise LiveTradingError("Cannot enter: missing reference price")

        base_qty, quote_est = plan_entry_base_qty(
            symbol=symbol,
            notional_usdt=notional,
            reference_price=ref_price,
            perp_client=perp_client,
            spot_client=spot_client,
        )
        validate_spot_buy_balance(spot_client=spot_client, quote_required=quote_est)

        spot_result = None
        perp_result = None
        try:
            spot_result = self._place_order(
                spot_client,
                symbol=symbol,
                side="BUY",
                quantity=base_qty,
                client_order_id=f"ha{self.strategy_id}s",
                for_entry=True,
            )
            spot_filled = float(spot_result.filled or 0.0)
            if spot_filled <= 0:
                raise LiveTradingError("Spot leg filled zero quantity")

            hedge_qty = align_dual_leg_qty(
                symbol=symbol,
                quantity=min(spot_filled, base_qty),
                spot_client=spot_client,
                perp_client=perp_client,
            )
            if hedge_qty <= 0:
                raise LiveTradingError(
                    f"Aligned hedge qty is zero after spot fill ({spot_filled:g}); "
                    f"increase notional"
                )

            perp_result = self._place_order(
                perp_client,
                symbol=symbol,
                side="SELL",
                quantity=hedge_qty,
                position_side="SHORT",
                client_order_id=f"ha{self.strategy_id}p",
                for_entry=True,
            )
            perp_filled = float(perp_result.filled or 0.0)
            if perp_filled <= 0:
                raise LiveTradingError(
                    f"Perp leg filled zero quantity (requested={hedge_qty:g}); "
                    "check futures margin / position mode"
                )

            spot_qty, perp_qty = self._sync_matched_base_qty(
                spot_client, perp_client, symbol, context="en",
            )
            if spot_qty <= 0 or perp_qty <= 0:
                raise LiveTradingError("Leg sync failed after entry")
            if abs(base_qty_gap(spot_qty, perp_qty)) > 1e-8:
                append_strategy_log(
                    self.strategy_id,
                    "warning",
                    f"Hedge qty mismatch after sync: spot={spot_qty:.8f} perp={perp_qty:.8f}",
                )

        except Exception as e:
            self._compensate_partial(spot_client, perp_client, symbol, spot_result, perp_result)
            err = str(e)
            state.status = "flat"
            state.last_error = err
            self.state_repo.upsert(state)
            append_strategy_log(self.strategy_id, "error", f"Hedge enter failed: {err}")
            raise LiveTradingError(err) from e

        new_state = HedgeArbState(
            strategy_id=self.strategy_id,
            status="holding",
            symbol=symbol,
            spot_qty=spot_qty,
            perp_qty=perp_qty,
            entry_basis_pct=signals.basis_pct,
            entry_funding_rate=signals.funding_rate,
            entered_at=utc_now_iso(),
            last_error="",
        )
        self.state_repo.upsert(new_state)
        append_strategy_log(
            self.strategy_id,
            "info",
            f"Hedge entered {symbol}: spot={spot_qty:.6f} perp_short={perp_qty:.6f} "
            f"(matched qty, planned={base_qty:.6f}) "
            f"funding={signals.funding_rate:.6f} basis={signals.basis_pct:.4%}",
        )
        return {"ok": True, "spot_qty": spot_qty, "perp_qty": perp_qty, "status": self.get_status()}

    def exit(self) -> Dict[str, Any]:
        symbol = self._symbol()
        state = self.state_repo.ensure_row(self.strategy_id, symbol)
        spot_client = self._spot_client()
        perp_client = self._perp_client()

        try:
            spot_qty, perp_qty = self._sync_matched_base_qty(
                spot_client, perp_client, symbol, context="ex",
            )
        except Exception as e:
            logger.warning("hedge_arb exit sync sid=%s: %s", self.strategy_id, e)
            spot_qty, perp_qty = read_live_legs(spot_client, perp_client, symbol)

        if spot_qty <= 0 and perp_qty <= 0:
            flat = HedgeArbState(
                strategy_id=self.strategy_id,
                status="flat",
                symbol=symbol,
                spot_qty=0.0,
                perp_qty=0.0,
                last_error="",
            )
            self.state_repo.upsert(flat)
            return {"ok": True, "reason": "already_flat", "status": self.get_status()}

        errors = []
        close_qty = min(spot_qty, perp_qty) if spot_qty > 0 and perp_qty > 0 else max(spot_qty, perp_qty)
        if perp_qty > 0 and close_qty > 0:
            try:
                perp_client.place_market_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=close_qty,
                    reduce_only=True,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}px",
                )
            except Exception as e:
                errors.append(f"perp_close: {e}")

        if spot_qty > 0 and close_qty > 0:
            try:
                spot_client.place_market_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=close_qty,
                    client_order_id=f"ha{self.strategy_id}sx",
                )
            except Exception as e:
                errors.append(f"spot_close: {e}")

        live_spot, live_perp = read_live_legs(spot_client, perp_client, symbol)
        new_status = "flat" if live_spot <= 1e-12 and live_perp <= 1e-12 else "holding"
        new_state = HedgeArbState(
            strategy_id=self.strategy_id,
            status=new_status,
            symbol=symbol,
            spot_qty=live_spot,
            perp_qty=live_perp,
            last_error="; ".join(errors),
        )
        self.state_repo.upsert(new_state)
        if errors:
            append_strategy_log(self.strategy_id, "warning", f"Hedge exit partial: {'; '.join(errors)}")
            return {"ok": False, "errors": errors, "status": self.get_status()}
        append_strategy_log(self.strategy_id, "info", f"Hedge exited {symbol}")
        return {"ok": True, "status": self.get_status()}

    def rebalance(self) -> Dict[str, Any]:
        symbol = self._symbol()
        state = self.state_repo.ensure_row(self.strategy_id, symbol)
        signals = self.get_signals()
        spot_client = self._spot_client()
        perp_client = self._perp_client()
        spot_qty, perp_qty = read_live_legs(spot_client, perp_client, symbol)

        if spot_qty <= 0 and perp_qty <= 0:
            return {"ok": False, "reason": "flat", "status": self.get_status()}

        drift = notional_drift_pct(
            spot_qty, signals.spot_price, perp_qty, signals.perp_mark_price,
        )
        _, qty_drift_pct, _ = qty_drift_metrics(spot_qty, perp_qty)
        if (
            drift < self.config.rebalance_threshold_pct
            and qty_drift_pct < self.config.rebalance_threshold_pct
        ):
            return {"ok": True, "reason": "within_threshold", "drift_pct": drift, "status": self.get_status()}

        delta_base = base_qty_gap(spot_qty, perp_qty)
        if abs(delta_base) <= 0:
            spot_qty, perp_qty = self._sync_matched_base_qty(
                spot_client, perp_client, symbol, context="rb",
            )
            state.spot_qty = spot_qty
            state.perp_qty = perp_qty
            state.last_rebalance_at = utc_now_iso()
            state.last_error = ""
            self.state_repo.upsert(state)
            return {"ok": True, "reason": "qty_sync", "status": self.get_status()}

        try:
            if delta_base > 0:
                add_qty = align_dual_leg_qty(
                    symbol=symbol,
                    quantity=abs(delta_base),
                    spot_client=spot_client,
                    perp_client=perp_client,
                )
                if add_qty <= 0:
                    return {"ok": False, "reason": "qty_below_step", "status": self.get_status()}
                self._place_order(
                    perp_client,
                    symbol=symbol,
                    side="SELL",
                    quantity=add_qty,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}rb",
                )
            else:
                reduce_qty = align_dual_leg_qty(
                    symbol=symbol,
                    quantity=abs(delta_base),
                    spot_client=spot_client,
                    perp_client=perp_client,
                )
                if reduce_qty <= 0:
                    return {"ok": False, "reason": "qty_below_step", "status": self.get_status()}
                self._place_order(
                    perp_client,
                    symbol=symbol,
                    side="BUY",
                    quantity=reduce_qty,
                    reduce_only=True,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}rb",
                )
        except Exception as e:
            state.last_error = str(e)
            self.state_repo.upsert(state)
            raise LiveTradingError(str(e)) from e

        spot_qty, perp_qty = self._sync_matched_base_qty(
            spot_client, perp_client, symbol, context="rb",
        )
        state.spot_qty = spot_qty
        state.perp_qty = perp_qty
        state.last_rebalance_at = utc_now_iso()
        state.last_error = ""
        self.state_repo.upsert(state)
        append_strategy_log(
            self.strategy_id,
            "info",
            f"Hedge rebalanced {symbol}: drift={drift:.2%} delta_base={delta_base:.6f}",
        )
        return {"ok": True, "drift_pct": drift, "delta_base": delta_base, "status": self.get_status()}

    def _compensate_partial(
        self,
        spot_client: BinanceSpotClient,
        perp_client: BinanceFuturesClient,
        symbol: str,
        spot_result: Any,
        perp_result: Any,
    ) -> None:
        spot_filled = float(getattr(spot_result, "filled", 0.0) or 0.0) if spot_result else 0.0
        perp_filled = float(getattr(perp_result, "filled", 0.0) or 0.0) if perp_result else 0.0
        if spot_filled > 0 and perp_filled <= 0:
            try:
                spot_client.place_market_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=spot_filled,
                    client_order_id=f"ha{self.strategy_id}cp",
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
                perp_client.place_market_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=perp_filled,
                    reduce_only=True,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}cp",
                )
                append_strategy_log(
                    self.strategy_id,
                    "warning",
                    f"Compensated orphan perp leg: closed {perp_filled:.6f}",
                )
            except Exception as e:
                logger.error("hedge_arb compensate perp sid=%s: %s", self.strategy_id, e)
