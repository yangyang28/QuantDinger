"""Regime JSON contract (PRD §3.3) — validate before any strategy routing."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


REGIME_SCHEMA_VERSION = "ai-auto-regime-v1"

VALID_REGIMES = frozenset({"ARBITRAGE", "TREND", "RANGE", "RISK_OFF"})
VALID_SHOCKS = frozenset({"none", "low", "medium", "high"})
VALID_BIASES = frozenset({"bull", "bear", "neutral", "funding_arb"})

# Strategy tags used by the router / PRD matrix
STRATEGY_XAU_FUNDING = "XAU_FUNDING"
STRATEGY_GRID_BTC = "GRID_BTC"
STRATEGY_OPP_TREND = "OPP_TREND"
STRATEGY_FUNDING_CRYPTO = "FUNDING_CRYPTO"


@dataclass
class AssetBias:
    bias: str = "neutral"
    box: Optional[List[float]] = None
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "bias": self.bias,
            "confidence": round(float(self.confidence), 4),
        }
        if self.box and len(self.box) >= 2:
            d["box"] = [float(self.box[0]), float(self.box[1])]
        return d


@dataclass
class RegimeDecision:
    ts: str
    regime: str
    assets: Dict[str, AssetBias] = field(default_factory=dict)
    scores: Dict[str, float] = field(default_factory=dict)
    event_shock: str = "none"
    allowed_strategies: List[str] = field(default_factory=list)
    blocked_strategies: List[str] = field(default_factory=list)
    rationale_zh: str = ""
    valid_until_min: int = 30
    schema_version: str = REGIME_SCHEMA_VERSION
    source: str = "llm"  # llm | fallback | cached
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "regime": self.regime,
            "assets": {k: v.to_dict() for k, v in self.assets.items()},
            "scores": {k: round(float(v), 4) for k, v in self.scores.items()},
            "event_shock": self.event_shock,
            "allowed_strategies": list(self.allowed_strategies),
            "blocked_strategies": list(self.blocked_strategies),
            "rationale_zh": self.rationale_zh,
            "valid_until_min": int(self.valid_until_min),
            "schema_version": self.schema_version,
            "source": self.source,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def parse_regime_payload(payload: Any, *, source: str = "llm") -> RegimeDecision:
    """Parse and validate a regime JSON object. Raises ValueError on hard failures."""
    if not isinstance(payload, dict):
        raise ValueError("regime payload must be a JSON object")

    regime = str(payload.get("regime") or "").strip().upper()
    if regime not in VALID_REGIMES:
        raise ValueError(f"invalid regime: {regime!r}")

    shock = str(payload.get("event_shock") or "none").strip().lower()
    if shock not in VALID_SHOCKS:
        raise ValueError(f"invalid event_shock: {shock!r}")

    scores_in = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
    scores = {
        "technical": _clamp01(scores_in.get("technical"), 0.5),
        "news": _clamp01(scores_in.get("news"), 0.5),
        "event": _clamp01(scores_in.get("event"), 0.5),
        "sentiment": _clamp01(scores_in.get("sentiment"), 0.5),
    }

    assets: Dict[str, AssetBias] = {}
    assets_in = payload.get("assets") if isinstance(payload.get("assets"), dict) else {}
    for key, val in assets_in.items():
        if not isinstance(val, dict):
            continue
        bias = str(val.get("bias") or "neutral").strip().lower()
        if bias not in VALID_BIASES:
            bias = "neutral"
        box = val.get("box")
        box_list: Optional[List[float]] = None
        if isinstance(box, (list, tuple)) and len(box) >= 2:
            try:
                box_list = [float(box[0]), float(box[1])]
            except (TypeError, ValueError):
                box_list = None
        assets[str(key).upper()] = AssetBias(
            bias=bias,
            box=box_list,
            confidence=_clamp01(val.get("confidence"), 0.0),
        )

    allowed = [
        str(x).strip().upper()
        for x in (payload.get("allowed_strategies") or [])
        if str(x).strip()
    ]
    blocked = [
        str(x).strip().upper()
        for x in (payload.get("blocked_strategies") or [])
        if str(x).strip()
    ]

    try:
        valid_until = int(payload.get("valid_until_min") or 30)
    except (TypeError, ValueError):
        valid_until = 30
    valid_until = max(5, min(240, valid_until))

    ts = str(payload.get("ts") or "").strip() or _now_iso()

    return RegimeDecision(
        ts=ts,
        regime=regime,
        assets=assets,
        scores=scores,
        event_shock=shock,
        allowed_strategies=allowed,
        blocked_strategies=blocked,
        rationale_zh=str(payload.get("rationale_zh") or "")[:2000],
        valid_until_min=valid_until,
        schema_version=REGIME_SCHEMA_VERSION,
        source=source,
        raw=dict(payload),
    )


def risk_off_fallback(*, rationale: str, source: str = "fallback") -> RegimeDecision:
    return RegimeDecision(
        ts=_now_iso(),
        regime="RISK_OFF",
        scores={"technical": 0.5, "news": 0.5, "event": 0.5, "sentiment": 0.5},
        event_shock="medium",
        allowed_strategies=[],
        blocked_strategies=[STRATEGY_OPP_TREND, STRATEGY_GRID_BTC],
        rationale_zh=rationale[:2000] or "AI 失效，强制 RISK_OFF",
        valid_until_min=15,
        source=source,
    )


def default_matrix_strategies(regime: str) -> List[str]:
    """PRD §5.4 scheduling matrix defaults when LLM omits allowed_strategies."""
    r = (regime or "").upper()
    if r == "ARBITRAGE":
        return [STRATEGY_XAU_FUNDING, STRATEGY_FUNDING_CRYPTO]
    if r == "RANGE":
        return [STRATEGY_XAU_FUNDING, STRATEGY_FUNDING_CRYPTO, STRATEGY_GRID_BTC]
    if r == "TREND":
        return [STRATEGY_XAU_FUNDING, STRATEGY_FUNDING_CRYPTO, STRATEGY_OPP_TREND]
    return []
