"""Config for Binance BTC spot long + perp short 1:1 arb bot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


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
class BinanceBtcArbConfig:
    symbol: str
    currency: str
    spot_usdt: float
    perp_notional_usdt: float
    leverage: int
    pre_exit_pct: float
    tick_interval_sec: int
    min_sell_qty: float
    spot_fee_rate: float
    perp_fee_rate: float
    align_1to1: bool


def parse_binance_btc_arb_config(trading_config: Dict[str, Any]) -> BinanceBtcArbConfig:
    tc = trading_config if isinstance(trading_config, dict) else {}
    symbol = str(tc.get("symbol") or "BTC/USDT").strip()
    currency = str(tc.get("currency") or _base_currency(symbol)).lower()
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
    return BinanceBtcArbConfig(
        symbol=symbol,
        currency=currency,
        spot_usdt=spot_usdt,
        perp_notional_usdt=perp_notional,
        leverage=max(1, int(float(tc.get("leverage") or 2))),
        pre_exit_pct=float(tc.get("pre_exit_pct") or tc.get("pre_redeem_pct") or 0.005),
        tick_interval_sec=max(5, int(tc.get("tick_interval_sec") or 10)),
        min_sell_qty=float(tc.get("min_sell_qty") or 0.00001),
        spot_fee_rate=float(tc.get("spot_fee_rate") or 0.001),
        perp_fee_rate=float(tc.get("perp_fee_rate") or 0.0005),
        align_1to1=bool(tc.get("align_1to1", True)),
    )
