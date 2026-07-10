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
    # User-defined base quantities (preferred over notional_usdt).
    spot_qty: float = 0.0
    perp_qty: float = 0.0
    notional_usdt: float = 0.0  # legacy fallback when spot/perp qty unset
    entry_funding_rate: float = 0.0001
    exit_funding_rate: float = 0.0
    max_basis_pct: float = 0.005
    rebalance_threshold_pct: float = 0.02
    max_hold_hours: float = 0.0
    tick_interval_sec: int = 300
    leverage: float = 1.0
    entry_order_mode: str = "market"
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

    def effective_spot_qty(self, reference_price: float = 0.0) -> float:
        if float(self.spot_qty or 0.0) > 0:
            return float(self.spot_qty)
        if float(self.notional_usdt or 0.0) > 0 and float(reference_price or 0.0) > 0:
            return float(self.notional_usdt) / float(reference_price)
        return 0.0

    def effective_perp_qty(self, reference_price: float = 0.0) -> float:
        if float(self.perp_qty or 0.0) > 0:
            return float(self.perp_qty)
        if float(self.notional_usdt or 0.0) > 0 and float(reference_price or 0.0) > 0:
            return float(self.notional_usdt) / float(reference_price)
        return 0.0


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
    mode = str(raw or "market").strip().lower()
    if mode in ("best", "best_price", "opponent", "最优", "最优价"):
        return "best"
    if mode in ("market", "taker"):
        return "market"
    if mode in ("maker", "limit", "limit_first", "maker_then_market"):
        return "best"
    return "market"


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
            qty = _float(item.get("qty") or item.get("quantity"), 0.0)
            if mt in ("spot", "swap") and role in ("long", "short"):
                legs.append(HedgeLegConfig(market_type=mt, symbol=sym, role=role))

    spot_qty = _float(tc.get("spot_qty") or tc.get("spot_quantity"), 0.0)
    perp_qty = _float(tc.get("perp_qty") or tc.get("perp_quantity") or tc.get("swap_qty"), 0.0)
    if isinstance(legs_raw, list):
        for item in legs_raw:
            if not isinstance(item, dict):
                continue
            mt = str(item.get("market_type") or "").strip().lower()
            if mt in ("futures", "future", "perp", "perpetual"):
                mt = "swap"
            role = str(item.get("role") or "").strip().lower()
            leg_qty = _float(item.get("qty") or item.get("quantity"), 0.0)
            if leg_qty <= 0:
                continue
            if mt == "spot" and role == "long" and spot_qty <= 0:
                spot_qty = leg_qty
            if mt == "swap" and role == "short" and perp_qty <= 0:
                perp_qty = leg_qty

    if not legs:
        legs = [
            HedgeLegConfig(market_type="spot", symbol=symbol, role="long"),
            HedgeLegConfig(market_type="swap", symbol=symbol, role="short"),
        ]

    notional_default = 1000.0 if spot_qty <= 0 and perp_qty <= 0 else 0.0

    return HedgeArbConfig(
        symbol=symbol,
        spot_qty=spot_qty,
        perp_qty=perp_qty,
        notional_usdt=_float(tc.get("notional_usdt"), notional_default),
        entry_funding_rate=_float(tc.get("entry_funding_rate"), 0.0001),
        exit_funding_rate=_float(tc.get("exit_funding_rate"), 0.0),
        max_basis_pct=_float(tc.get("max_basis_pct"), 0.005),
        rebalance_threshold_pct=_float(tc.get("rebalance_threshold_pct"), 0.02),
        max_hold_hours=_float(tc.get("max_hold_hours"), 0.0),
        tick_interval_sec=max(60, _int(tc.get("tick_interval_sec"), 300)),
        leverage=max(1.0, _float(tc.get("leverage"), 1.0)),
        entry_order_mode=_normalize_entry_order_mode(
            tc.get("entry_order_mode") or tc.get("order_mode") or "market"
        ),
        legs=legs,
    )
