"""Two-leg enter / exit / rebalance with compensation on partial failure."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.exchange_execution import resolve_exchange_config
from app.services.hedge_arb.config import HedgeArbConfig, parse_hedge_arb_config
from app.services.hedge_arb.positions import read_live_legs
from app.services.hedge_arb.signals import HedgeArbSignals, collect_signals
from app.services.hedge_arb.sizing import (
    normalize_market_base_qty,
    notional_drift_pct,
    plan_entry_base_qty,
    rebalance_delta_base,
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
            spot_qty = float(spot_result.filled or 0.0)
            if spot_qty <= 0:
                raise LiveTradingError("Spot leg filled zero quantity")

            perp_qty_req = normalize_market_base_qty(
                perp_client, symbol=symbol, quantity=spot_qty,
            )
            if perp_qty_req <= 0:
                raise LiveTradingError(
                    f"Perp qty below min lot after spot fill: spot={spot_qty:.8f}, "
                    f"increase notional (BTC usually needs ≥120 USDT)"
                )

            perp_result = self._place_order(
                perp_client,
                symbol=symbol,
                side="SELL",
                quantity=perp_qty_req,
                position_side="SHORT",
                client_order_id=f"ha{self.strategy_id}p",
                for_entry=True,
            )
            perp_qty = float(perp_result.filled or 0.0)
            if perp_qty <= 0:
                raise LiveTradingError(
                    f"Perp leg filled zero quantity (requested={perp_qty_req:g}); "
                    "check futures margin / position mode"
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
            f"funding={signals.funding_rate:.6f} basis={signals.basis_pct:.4%}",
        )
        return {"ok": True, "spot_qty": spot_qty, "perp_qty": perp_qty, "status": self.get_status()}

    def exit(self) -> Dict[str, Any]:
        symbol = self._symbol()
        state = self.state_repo.ensure_row(self.strategy_id, symbol)
        spot_client = self._spot_client()
        perp_client = self._perp_client()
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
        if perp_qty > 0:
            try:
                perp_client.place_market_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=perp_qty,
                    reduce_only=True,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}px",
                )
            except Exception as e:
                errors.append(f"perp_close: {e}")

        if spot_qty > 0:
            try:
                spot_client.place_market_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=spot_qty,
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
        if drift < self.config.rebalance_threshold_pct:
            return {"ok": True, "reason": "within_threshold", "drift_pct": drift, "status": self.get_status()}

        delta_base = rebalance_delta_base(
            spot_qty, perp_qty, signals.spot_price, signals.perp_mark_price,
        )
        if abs(delta_base) <= 0:
            return {"ok": True, "reason": "no_delta", "status": self.get_status()}

        try:
            if delta_base > 0:
                perp_client.place_market_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=abs(delta_base),
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}rb",
                )
            else:
                perp_client.place_market_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=abs(delta_base),
                    reduce_only=True,
                    position_side="SHORT",
                    client_order_id=f"ha{self.strategy_id}rb",
                )
        except Exception as e:
            state.last_error = str(e)
            self.state_repo.upsert(state)
            raise LiveTradingError(str(e)) from e

        live_spot, live_perp = read_live_legs(spot_client, perp_client, symbol)
        state.spot_qty = live_spot
        state.perp_qty = live_perp
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
