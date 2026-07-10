"""Multi-exchange adapter for hedge_arb spot long + perp short legs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.services.exchange_execution import resolve_exchange_config
from app.services.live_trading.base import LiveOrderResult, LiveTradingError
from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.execution import place_order_from_signal
from app.services.live_trading.factory import create_client, exchange_demo_mode_enabled
from app.services.live_trading.fill_recovery import try_recover_zero_fill
from app.services.live_trading.position_query import query_exchange_position_size
from app.services.pending_orders.live_order_phases import wait_live_order_fill
from app.utils.logger import get_logger

logger = get_logger(__name__)

_HEDGE_EXCHANGES = frozenset(
    {"binance", "okx", "htx", "huobi", "bybit", "bitget", "gate", "kraken"}
)


@dataclass
class HedgeExchangeContext:
    exchange_id: str
    exchange_config: Dict[str, Any]
    testnet: bool
    spot_client: Any
    perp_client: Any
    spot_symbol: str
    perp_symbol: str


def normalize_exchange_id(raw: Any) -> str:
    ex = str(raw or "binance").strip().lower()
    if ex == "huobi":
        return "htx"
    return ex


def assert_hedge_exchange_supported(exchange_id: str) -> None:
    ex = normalize_exchange_id(exchange_id)
    if ex not in _HEDGE_EXCHANGES:
        raise LiveTradingError(
            f"hedge_arb does not support exchange '{exchange_id}' yet; "
            f"supported: {', '.join(sorted(_HEDGE_EXCHANGES))}"
        )


def build_hedge_context(
    *,
    user_id: int,
    exchange_config: Dict[str, Any],
    spot_symbol: str,
    perp_symbol: str,
) -> HedgeExchangeContext:
    cfg = resolve_exchange_config(exchange_config or {}, user_id=int(user_id))
    exchange_id = normalize_exchange_id(cfg.get("exchange_id") or cfg.get("exchangeId"))
    assert_hedge_exchange_supported(exchange_id)
    spot_client = create_client(cfg, market_type="spot")
    perp_client = create_client(cfg, market_type="swap")
    return HedgeExchangeContext(
        exchange_id=exchange_id,
        exchange_config=cfg,
        testnet=exchange_demo_mode_enabled(cfg),
        spot_client=spot_client,
        perp_client=perp_client,
        spot_symbol=str(spot_symbol or "").strip(),
        perp_symbol=str(perp_symbol or spot_symbol or "").strip(),
    )


def read_live_legs(ctx: HedgeExchangeContext) -> Tuple[float, float]:
    spot = query_exchange_position_size(
        client=ctx.spot_client,
        symbol=ctx.spot_symbol,
        pos_side="long",
        market_type="spot",
        exchange_config=ctx.exchange_config,
    )
    perp = query_exchange_position_size(
        client=ctx.perp_client,
        symbol=ctx.perp_symbol,
        pos_side="short",
        market_type="swap",
        exchange_config=ctx.exchange_config,
    )
    return max(0.0, float(spot)), max(0.0, float(perp))


def _signal_for_leg(*, market_type: str, side: str, reduce_only: bool) -> str:
    sd = str(side or "").strip().lower()
    mt = str(market_type or "swap").strip().lower()
    ro = bool(reduce_only)
    if mt == "spot":
        if sd == "buy" and not ro:
            return "open_long"
        if sd == "sell" and ro:
            return "close_long"
        raise LiveTradingError(f"unsupported spot order side={side} reduce_only={reduce_only}")
    if sd == "sell" and not ro:
        return "open_short"
    if sd == "buy" and ro:
        return "close_short"
    if sd == "sell" and ro:
        return "close_short"
    if sd == "buy" and not ro:
        return "open_long"
    raise LiveTradingError(f"unsupported perp order side={side} reduce_only={reduce_only}")


def _maybe_binance_best_price(
    ctx: HedgeExchangeContext,
    *,
    client: Any,
    market_type: str,
    side: str,
    quantity: float,
    reduce_only: bool,
    position_side: Optional[str],
    client_order_id: Optional[str],
    for_entry: bool,
    entry_order_mode: str,
    force_market: bool,
) -> Optional[LiveOrderResult]:
    if force_market or entry_order_mode == "market" or not for_entry:
        return None
    if market_type != "spot" and not isinstance(client, BinanceFuturesClient):
        return None
    if market_type == "spot" and not isinstance(client, BinanceSpotClient):
        return None
    if not getattr(type(client), "place_best_price_order", None):
        return None
    kwargs: Dict[str, Any] = {
        "symbol": ctx.spot_symbol if market_type == "spot" else ctx.perp_symbol,
        "side": "BUY" if str(side).lower() == "buy" else "SELL",
        "quantity": float(quantity),
        "client_order_id": client_order_id,
    }
    if market_type != "spot":
        kwargs["reduce_only"] = reduce_only
        if position_side:
            kwargs["position_side"] = position_side
    return client.place_best_price_order(**kwargs)


def place_leg_order(
    ctx: HedgeExchangeContext,
    *,
    market_type: str,
    side: str,
    quantity: float,
    reduce_only: bool = False,
    client_order_id: Optional[str] = None,
    for_entry: bool = False,
    entry_order_mode: str = "market",
    force_market: bool = False,
    pre_position_qty: float = 0.0,
    ref_price: float = 0.0,
) -> LiveOrderResult:
    mt = str(market_type or "swap").strip().lower()
    qty = float(quantity or 0.0)
    if qty <= 0:
        raise LiveTradingError(f"invalid {mt} order quantity: {quantity}")

    client = ctx.spot_client if mt == "spot" else ctx.perp_client
    symbol = ctx.spot_symbol if mt == "spot" else ctx.perp_symbol
    pos_side = "short" if mt != "spot" and not reduce_only and str(side).lower() == "sell" else (
        "short" if mt != "spot" and reduce_only else "long"
    )

    best = _maybe_binance_best_price(
        ctx,
        client=client,
        market_type=mt,
        side=side,
        quantity=qty,
        reduce_only=reduce_only,
        position_side="SHORT" if pos_side == "short" else None,
        client_order_id=client_order_id,
        for_entry=for_entry,
        entry_order_mode=entry_order_mode,
        force_market=force_market or mt != "spot",
    )
    if best is not None:
        result = best
    else:
        signal = _signal_for_leg(market_type=mt, side=side, reduce_only=reduce_only)
        result = place_order_from_signal(
            client,
            signal_type=signal,
            symbol=symbol,
            amount=qty,
            market_type=mt,
            exchange_config=ctx.exchange_config,
            client_order_id=client_order_id,
        )

    return resolve_order_fill(
        ctx,
        client=client,
        market_type=mt,
        symbol=symbol,
        result=result,
        signal_type=_signal_for_leg(market_type=mt, side=side, reduce_only=reduce_only),
        pos_side=pos_side,
        requested_qty=qty,
        pre_position_qty=pre_position_qty,
        ref_price=ref_price,
        for_entry=for_entry,
        entry_order_mode=entry_order_mode,
        force_market=force_market or mt != "spot",
        side=side,
        reduce_only=reduce_only,
        client_order_id=client_order_id,
    )


def resolve_order_fill(
    ctx: HedgeExchangeContext,
    *,
    client: Any,
    market_type: str,
    symbol: str,
    result: LiveOrderResult,
    signal_type: str,
    pos_side: str,
    requested_qty: float,
    pre_position_qty: float,
    ref_price: float,
    for_entry: bool = False,
    entry_order_mode: str = "market",
    force_market: bool = False,
    side: str = "",
    reduce_only: bool = False,
    client_order_id: Optional[str] = None,
) -> LiveOrderResult:
    filled = float(result.filled or 0.0)
    avg_price = float(result.avg_price or 0.0)
    oid = str(result.exchange_order_id or "")
    raw = result.raw if isinstance(result.raw, dict) else {}
    coid = str(raw.get("clientOrderId") or raw.get("origClientOrderId") or client_order_id or "")

    if filled <= 0 and (oid or coid):
        try:
            info = wait_live_order_fill(
                client=client,
                symbol=symbol,
                order_id=oid,
                client_order_id=coid,
                market_type=market_type,
                exchange_config=ctx.exchange_config,
                max_wait_sec=12.0,
                phase="market",
            )
            filled = float(info.get("filled") or 0.0)
            avg_price = float(info.get("avg_price") or avg_price or 0.0)
            if isinstance(info.get("order"), dict):
                raw = info["order"]
        except Exception as e:
            logger.debug("hedge_arb wait_for_fill failed symbol=%s: %s", symbol, e)

    if filled <= 0:
        rec_qty, rec_px, _src = try_recover_zero_fill(
            client,
            symbol=symbol,
            market_type=market_type,
            exchange_config=ctx.exchange_config,
            exchange_order_id=oid,
            client_order_id=coid,
            requested_qty=float(requested_qty or 0.0),
            signal_type=signal_type,
            pos_side=pos_side,
            pre_position_qty=float(pre_position_qty or 0.0),
            ref_price=float(ref_price or 0.0),
        )
        if rec_qty > 0:
            filled = rec_qty
            avg_price = rec_px or avg_price or ref_price

    if filled <= 0 and for_entry and market_type == "spot" and entry_order_mode != "market" and not force_market:
        signal = _signal_for_leg(market_type=market_type, side=side, reduce_only=reduce_only)
        retry = place_order_from_signal(
            client,
            signal_type=signal,
            symbol=symbol,
            amount=float(requested_qty or 0.0),
            market_type=market_type,
            exchange_config=ctx.exchange_config,
            client_order_id=f"{client_order_id or ''}m"[:36] or None,
        )
        return resolve_order_fill(
            ctx,
            client=client,
            market_type=market_type,
            symbol=symbol,
            result=retry,
            signal_type=signal,
            pos_side=pos_side,
            requested_qty=requested_qty,
            pre_position_qty=pre_position_qty,
            ref_price=ref_price,
            for_entry=True,
            entry_order_mode="market",
            force_market=True,
            side=side,
            reduce_only=reduce_only,
            client_order_id=client_order_id,
        )

    return LiveOrderResult(
        exchange_id=str(result.exchange_id or ctx.exchange_id),
        exchange_order_id=oid,
        filled=filled,
        avg_price=avg_price,
        raw=raw if isinstance(raw, dict) else result.raw,
    )


def set_perp_leverage(ctx: HedgeExchangeContext, *, leverage: float, symbol: Optional[str] = None) -> None:
    client = ctx.perp_client
    if not getattr(client, "set_leverage", None):
        return
    sym = str(symbol or ctx.perp_symbol)
    try:
        client.set_leverage(symbol=sym, leverage=float(leverage or 1.0))
    except Exception as e:
        logger.warning("hedge_arb set_leverage ex=%s sym=%s: %s", ctx.exchange_id, sym, e)
