"""Config for HTX earn + short hedge bot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.services.live_trading.symbols import to_htx_contract_code, to_htx_spot_symbol


def _base_currency(symbol: str) -> str:
    s = str(symbol or "").strip()
    if ":" in s:
        s = s.split(":", 1)[0]
    if "/" in s:
        return s.split("/", 1)[0].strip().lower()
    for quote in ("usdt", "usdc", "usd", "btc", "eth"):
        if s.lower().endswith(quote) and len(s) > len(quote):
            return s[:-len(quote)].lower()
    return s.lower()


@dataclass
class HtxEarnHedgeConfig:
    symbol: str
    currency: str
    spot_symbol: str
    swap_symbol: str
    spot_usdt: float
    perp_notional_usdt: float
    leverage: int
    pre_redeem_pct: float
    emergency_redeem_pct: float
    maintenance_pre_redeem_pct: float
    tick_interval_sec: int
    min_sell_qty: float
    spot_fee_rate: float
    perp_fee_rate: float
    align_1to1: bool


def parse_htx_earn_hedge_config(trading_config: Dict[str, Any]) -> HtxEarnHedgeConfig:
    tc = trading_config if isinstance(trading_config, dict) else {}
    symbol = str(tc.get("symbol") or "TRUMP/USDT").strip()
    currency = str(tc.get("currency") or _base_currency(symbol)).lower()
    # Prefer explicit capitals; legacy aliases kept for older strategies.
    spot_usdt = float(
        tc.get("spot_usdt")
        or tc.get("spot_capital_usdt")
        or tc.get("spot_notional_usdt")
        or 2000
    )
    perp_notional = float(
        tc.get("perp_notional_usdt")
        or tc.get("perp_capital_usdt")
        or tc.get("contract_capital_usdt")
        or tc.get("perp_usdt")
        or 2000
    )
    return HtxEarnHedgeConfig(
        symbol=symbol,
        currency=currency,
        spot_symbol=str(tc.get("spot_symbol") or to_htx_spot_symbol(symbol)),
        swap_symbol=str(tc.get("swap_symbol") or to_htx_contract_code(symbol)),
        # Defaults: spot 2000U; perp notional 2000U (margin = notional / leverage)
        spot_usdt=spot_usdt,
        perp_notional_usdt=perp_notional,
        leverage=max(1, int(float(tc.get("leverage") or 2))),
        pre_redeem_pct=float(tc.get("pre_redeem_pct") or 0.005),
        emergency_redeem_pct=float(tc.get("emergency_redeem_pct") or 0.0025),
        maintenance_pre_redeem_pct=float(tc.get("maintenance_pre_redeem_pct") or 0.01),
        tick_interval_sec=max(5, int(tc.get("tick_interval_sec") or 10)),
        min_sell_qty=float(tc.get("min_sell_qty") or 0.01),
        spot_fee_rate=float(tc.get("spot_fee_rate") or 0.002),
        perp_fee_rate=float(tc.get("perp_fee_rate") or 0.0005),
        align_1to1=bool(tc.get("align_1to1", True)),
    )
