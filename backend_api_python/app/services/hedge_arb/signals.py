"""Public-market signals for funding-rate / basis hedge decisions (multi-exchange)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from app.services.hedge_arb.exchange_adapter import normalize_exchange_id
from app.services.live_trading.base import _get_requests_verify
from app.services.live_trading.symbols import (
    to_binance_futures_symbol,
    to_bitget_um_symbol,
    to_gate_currency_pair,
    to_okx_swap_inst_id,
)


@dataclass
class HedgeArbSignals:
    symbol: str
    funding_rate: float
    spot_price: float
    perp_mark_price: float
    basis_pct: float
    source: str = "public"
    exchange_id: str = "binance"


def _public_get(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    resp = requests.get(url, params=params or {}, timeout=10, verify=_get_requests_verify())
    resp.raise_for_status()
    return resp.json()


def _num(raw: Any) -> float:
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def compute_basis_pct(spot_price: float, perp_price: float) -> float:
    if spot_price <= 0:
        return 0.0
    return (float(perp_price) - float(spot_price)) / float(spot_price)


# --- Binance ---

def _binance_signals(symbol: str, *, testnet: bool = False) -> HedgeArbSignals:
    pair = to_binance_futures_symbol(symbol)
    fapi = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
    spot_api = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
    funding = 0.0
    perp = 0.0
    try:
        idx = _public_get(f"{fapi}/fapi/v1/premiumIndex", params={"symbol": pair})
        if isinstance(idx, dict):
            funding = _num(idx.get("lastFundingRate"))
            perp = _num(idx.get("markPrice"))
    except Exception:
        pass
    spot = 0.0
    try:
        px = _public_get(f"{spot_api}/api/v3/ticker/price", params={"symbol": pair})
        if isinstance(px, dict):
            spot = _num(px.get("price"))
    except Exception:
        pass
    if perp <= 0:
        perp = spot
    return HedgeArbSignals(
        symbol=symbol,
        funding_rate=funding,
        spot_price=spot,
        perp_mark_price=perp,
        basis_pct=compute_basis_pct(spot, perp),
        source="binance_public",
        exchange_id="binance",
    )


# --- OKX ---

def _okx_signals(symbol: str) -> HedgeArbSignals:
    spot_inst = symbol.upper().replace("/", "-")
    swap_inst = to_okx_swap_inst_id(symbol)
    base = "https://www.okx.com"
    funding = 0.0
    try:
        raw = _public_get(f"{base}/api/v5/public/funding-rate", params={"instId": swap_inst})
        rows = (raw.get("data") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            funding = _num(rows[0].get("fundingRate"))
    except Exception:
        pass
    spot = 0.0
    try:
        raw = _public_get(f"{base}/api/v5/market/ticker", params={"instId": spot_inst})
        rows = (raw.get("data") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            spot = _num(rows[0].get("last") or rows[0].get("idxPx"))
    except Exception:
        pass
    perp = 0.0
    try:
        raw = _public_get(f"{base}/api/v5/market/ticker", params={"instId": swap_inst})
        rows = (raw.get("data") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            perp = _num(rows[0].get("markPx") or rows[0].get("last"))
    except Exception:
        pass
    if perp <= 0:
        perp = spot
    return HedgeArbSignals(
        symbol=symbol,
        funding_rate=funding,
        spot_price=spot,
        perp_mark_price=perp,
        basis_pct=compute_basis_pct(spot, perp),
        source="okx_public",
        exchange_id="okx",
    )


# --- HTX / Huobi ---

def _htx_signals(symbol: str) -> HedgeArbSignals:
    base_ccy = symbol.split("/")[0].lower() if "/" in symbol else symbol.replace("USDT", "").lower()
    contract = symbol.upper().replace("/", "-")
    spot_sym = f"{base_ccy}usdt"
    funding = 0.0
    perp = 0.0
    try:
        raw = _public_get(
            "https://api.hbdm.com/linear-swap-api/v1/swap_funding_rate",
            params={"contract_code": contract},
        )
        if isinstance(raw, dict):
            data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            if isinstance(data, dict):
                funding = _num(data.get("funding_rate"))
    except Exception:
        pass
    try:
        raw = _public_get(
            "https://api.hbdm.com/linear-swap-ex/market/detail/merged",
            params={"contract_code": contract},
        )
        if isinstance(raw, dict):
            tick = raw.get("tick") if isinstance(raw.get("tick"), dict) else {}
            perp = _num(tick.get("close") or tick.get("open"))
    except Exception:
        pass
    spot = 0.0
    try:
        raw = _public_get("https://api.huobi.pro/market/detail/merged", params={"symbol": spot_sym})
        if isinstance(raw, dict):
            tick = raw.get("tick") if isinstance(raw.get("tick"), dict) else {}
            spot = _num(tick.get("close") or tick.get("open"))
    except Exception:
        pass
    if perp <= 0:
        perp = spot
    return HedgeArbSignals(
        symbol=symbol,
        funding_rate=funding,
        spot_price=spot,
        perp_mark_price=perp,
        basis_pct=compute_basis_pct(spot, perp),
        source="htx_public",
        exchange_id="htx",
    )


# --- Bybit ---

def _bybit_signals(symbol: str) -> HedgeArbSignals:
    linear = symbol.replace("/", "").replace("-", "").upper()
    funding = 0.0
    perp = 0.0
    spot = 0.0
    try:
        raw = _public_get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": linear},
        )
        rows = ((raw.get("result") or {}).get("list") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            row = rows[0]
            funding = _num(row.get("fundingRate"))
            perp = _num(row.get("markPrice") or row.get("lastPrice"))
    except Exception:
        pass
    try:
        raw = _public_get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot", "symbol": linear},
        )
        rows = ((raw.get("result") or {}).get("list") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            spot = _num(rows[0].get("lastPrice"))
    except Exception:
        pass
    if perp <= 0:
        perp = spot
    return HedgeArbSignals(
        symbol=symbol,
        funding_rate=funding,
        spot_price=spot,
        perp_mark_price=perp,
        basis_pct=compute_basis_pct(spot, perp),
        source="bybit_public",
        exchange_id="bybit",
    )


# --- Bitget ---

def _bitget_signals(symbol: str) -> HedgeArbSignals:
    sym = to_bitget_um_symbol(symbol)
    funding = 0.0
    perp = 0.0
    spot = 0.0
    try:
        raw = _public_get(
            "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
            params={"symbol": sym, "productType": "USDT-FUTURES"},
        )
        rows = (raw.get("data") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            funding = _num(rows[0].get("fundingRate"))
    except Exception:
        pass
    try:
        raw = _public_get(
            "https://api.bitget.com/api/v2/mix/market/ticker",
            params={"symbol": sym, "productType": "USDT-FUTURES"},
        )
        rows = (raw.get("data") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            perp = _num(rows[0].get("markPrice") or rows[0].get("lastPr"))
    except Exception:
        pass
    try:
        raw = _public_get(
            "https://api.bitget.com/api/v2/spot/market/tickers",
            params={"symbol": sym},
        )
        rows = (raw.get("data") or []) if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            spot = _num(rows[0].get("lastPr") or rows[0].get("close"))
    except Exception:
        pass
    if perp <= 0:
        perp = spot
    return HedgeArbSignals(
        symbol=symbol,
        funding_rate=funding,
        spot_price=spot,
        perp_mark_price=perp,
        basis_pct=compute_basis_pct(spot, perp),
        source="bitget_public",
        exchange_id="bitget",
    )


# --- Gate ---

def _gate_signals(symbol: str) -> HedgeArbSignals:
    contract = to_gate_currency_pair(symbol)
    funding = 0.0
    perp = 0.0
    spot = 0.0
    try:
        raw = _public_get(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{contract}")
        if isinstance(raw, dict):
            funding = _num(raw.get("funding_rate"))
            perp = _num(raw.get("mark_price") or raw.get("last_price"))
    except Exception:
        pass
    try:
        raw = _public_get(
            "https://api.gateio.ws/api/v4/spot/tickers",
            params={"currency_pair": contract},
        )
        rows = raw if isinstance(raw, list) else []
        if rows and isinstance(rows[0], dict):
            spot = _num(rows[0].get("last"))
    except Exception:
        pass
    if perp <= 0:
        perp = spot
    return HedgeArbSignals(
        symbol=symbol,
        funding_rate=funding,
        spot_price=spot,
        perp_mark_price=perp,
        basis_pct=compute_basis_pct(spot, perp),
        source="gate_public",
        exchange_id="gate",
    )


def collect_signals(
    symbol: str,
    *,
    exchange_id: str = "binance",
    testnet: bool = False,
) -> HedgeArbSignals:
    ex = normalize_exchange_id(exchange_id)
    if ex == "binance":
        return _binance_signals(symbol, testnet=testnet)
    if ex == "okx":
        return _okx_signals(symbol)
    if ex == "htx":
        return _htx_signals(symbol)
    if ex == "bybit":
        return _bybit_signals(symbol)
    if ex == "bitget":
        return _bitget_signals(symbol)
    if ex == "gate":
        return _gate_signals(symbol)
    return _binance_signals(symbol, testnet=testnet)


def fetch_historical_funding(
    symbol: str,
    *,
    exchange_id: str = "binance",
    limit: int = 500,
    testnet: bool = False,
) -> List[dict]:
    ex = normalize_exchange_id(exchange_id)
    if ex != "binance":
        return []
    pair = to_binance_futures_symbol(symbol)
    base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
    lim = max(1, min(1000, int(limit or 500)))
    data = _public_get(f"{base}/fapi/v1/fundingRate", params={"symbol": pair, "limit": lim})
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            out.append({
                "funding_time_ms": int(row.get("fundingTime") or 0),
                "funding_rate": float(row.get("fundingRate") or 0.0),
            })
        except (TypeError, ValueError):
            continue
    return out


def should_enter(signals: HedgeArbSignals, *, entry_funding_rate: float, max_basis_pct: float) -> bool:
    if signals.funding_rate < entry_funding_rate:
        return False
    if max_basis_pct > 0 and abs(signals.basis_pct) > max_basis_pct:
        return False
    return signals.spot_price > 0 and signals.perp_mark_price > 0


def should_exit(
    signals: HedgeArbSignals,
    *,
    exit_funding_rate: float,
    max_basis_pct: float,
    hold_hours: float = 0.0,
    max_hold_hours: float = 0.0,
) -> bool:
    if signals.funding_rate < exit_funding_rate:
        return True
    if max_basis_pct > 0 and abs(signals.basis_pct) > max_basis_pct * 2:
        return True
    if max_hold_hours > 0 and hold_hours >= max_hold_hours:
        return True
    return False
