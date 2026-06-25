"""Parse hedge-arb settings from strategy trading_config."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class HedgeLegConfig:
    market_type: str
    symbol: str
    role: str  # long | short


@dataclass
class HedgeArbConfig:
    symbol: str = "BTC/USDT"
    notional_usdt: float = 1000.0
    entry_funding_rate: float = 0.0001
    exit_funding_rate: float = 0.0
    max_basis_pct: float = 0.005
    rebalance_threshold_pct: float = 0.02
    max_hold_hours: float = 0.0
    tick_interval_sec: int = 300
    leverage: float = 1.0
    # Entry execution: best = Binance 最优/对手价 (IOC+priceMatch), market = plain MARKET.
    entry_order_mode: str = "best"
    legs: List[HedgeLegConfig] = field(default_factory=list)

    def spot_symbol(self) -> str:
        for leg in self.legs:
            if leg.market_type == "spot":
                return leg.symbol
        return self.symbol

    def swap_symbol(self) -> str:
        for leg in self.legs:
            if leg.market_type == "swap":
                return leg.symbol
        return self.symbol


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_entry_order_mode(raw: Any) -> str:
    mode = str(raw or "best").strip().lower()
    if mode in ("best", "best_price", "opponent", "最优", "最优价"):
        return "best"
    if mode in ("market", "taker"):
        return "market"
    # Legacy bot wizard stored maker/limit for hedge_arb — treat as best-price entry.
    if mode in ("maker", "limit", "limit_first", "maker_then_market"):
        return "best"
    return "best"


def parse_hedge_arb_config(trading_config: Optional[Dict[str, Any]]) -> HedgeArbConfig:
    tc = trading_config if isinstance(trading_config, dict) else {}
    symbol = str(tc.get("symbol") or "BTC/USDT").strip()

    legs_raw = tc.get("hedge_legs")
    legs: List[HedgeLegConfig] = []
    if isinstance(legs_raw, list):
        for item in legs_raw:
            if not isinstance(item, dict):
                continue
            mt = str(item.get("market_type") or "").strip().lower()
            if mt in ("futures", "future", "perp", "perpetual"):
                mt = "swap"
            sym = str(item.get("symbol") or symbol).strip()
            role = str(item.get("role") or "").strip().lower()
            if mt in ("spot", "swap") and role in ("long", "short"):
                legs.append(HedgeLegConfig(market_type=mt, symbol=sym, role=role))

    if not legs:
        legs = [
            HedgeLegConfig(market_type="spot", symbol=symbol, role="long"),
            HedgeLegConfig(market_type="swap", symbol=symbol, role="short"),
        ]

    return HedgeArbConfig(
        symbol=symbol,
        notional_usdt=_float(tc.get("notional_usdt"), 1000.0),
        entry_funding_rate=_float(tc.get("entry_funding_rate"), 0.0001),
        exit_funding_rate=_float(tc.get("exit_funding_rate"), 0.0),
        max_basis_pct=_float(tc.get("max_basis_pct"), 0.005),
        rebalance_threshold_pct=_float(tc.get("rebalance_threshold_pct"), 0.02),
        max_hold_hours=_float(tc.get("max_hold_hours"), 0.0),
        tick_interval_sec=max(60, _int(tc.get("tick_interval_sec"), 300)),
        leverage=max(1.0, _float(tc.get("leverage"), 1.0)),
        entry_order_mode=_normalize_entry_order_mode(
            tc.get("entry_order_mode") or tc.get("order_mode") or "best"
        ),
        legs=legs,
    )
