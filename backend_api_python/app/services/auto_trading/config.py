"""Parse trading_config for bot_type=ai_auto."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


def _f(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _i(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True)
class AiAutoConfig:
    symbols: List[str]
    primary_symbol: str
    human_mode: str  # observe | confirm | auto
    tick_interval_sec: int
    regime_refresh_sec: int
    enable_funding_arb: bool
    enable_opportunity: bool
    enable_grid: bool
    use_llm: bool
    max_daily_loss_pct: float
    max_single_risk_pct: float
    kill_switch: bool
    funding_notional_usdt: float
    opportunity_risk_pct: float
    grid_sim_only: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "primary_symbol": self.primary_symbol,
            "human_mode": self.human_mode,
            "tick_interval_sec": self.tick_interval_sec,
            "regime_refresh_sec": self.regime_refresh_sec,
            "enable_funding_arb": self.enable_funding_arb,
            "enable_opportunity": self.enable_opportunity,
            "enable_grid": self.enable_grid,
            "use_llm": self.use_llm,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_single_risk_pct": self.max_single_risk_pct,
            "kill_switch": self.kill_switch,
            "funding_notional_usdt": self.funding_notional_usdt,
            "opportunity_risk_pct": self.opportunity_risk_pct,
            "grid_sim_only": self.grid_sim_only,
        }


def parse_ai_auto_config(trading_config: Dict[str, Any] | None) -> AiAutoConfig:
    tc = trading_config if isinstance(trading_config, dict) else {}
    symbols_raw = tc.get("symbols") or tc.get("symbol_list")
    symbols: List[str] = []
    if isinstance(symbols_raw, list):
        symbols = [str(s).strip().upper().replace("-", "/") for s in symbols_raw if str(s).strip()]
    primary = str(tc.get("symbol") or tc.get("primary_symbol") or "").strip().upper().replace("-", "/")
    if primary and primary not in symbols:
        symbols.insert(0, primary)
    if not symbols:
        symbols = ["BTC/USDT"]
    if not primary:
        primary = symbols[0]

    mode = str(tc.get("human_mode") or tc.get("mode") or "observe").strip().lower()
    if mode not in ("observe", "confirm", "auto"):
        mode = "observe"

    return AiAutoConfig(
        symbols=symbols,
        primary_symbol=primary,
        human_mode=mode,
        tick_interval_sec=max(60, _i(tc.get("tick_interval_sec"), 300)),
        regime_refresh_sec=max(60, _i(tc.get("regime_refresh_sec"), 900)),
        enable_funding_arb=bool(tc.get("enable_funding_arb", True)),
        enable_opportunity=bool(tc.get("enable_opportunity", True)),
        enable_grid=bool(tc.get("enable_grid", True)),
        use_llm=bool(tc.get("use_llm", True)),
        max_daily_loss_pct=_f(tc.get("max_daily_loss_pct"), 0.03),
        max_single_risk_pct=_f(tc.get("max_single_risk_pct"), 0.01),
        kill_switch=bool(tc.get("kill_switch", False)),
        funding_notional_usdt=max(0.0, _f(tc.get("funding_notional_usdt") or tc.get("notional_usdt"), 0.0)),
        opportunity_risk_pct=_f(tc.get("opportunity_risk_pct"), 0.01),
        # MVP: grid stays simulation / signal unless explicitly disabled
        grid_sim_only=bool(tc.get("grid_sim_only", True)),
    )
