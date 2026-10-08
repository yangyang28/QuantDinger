"""Collect a lightweight four-dimension feature bundle for the regime LLM."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_feature_bundle(
    *,
    symbols: List[str],
    primary_symbol: str,
    exchange_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Best-effort feature snapshot. Missing sources degrade gracefully."""
    technical: Dict[str, Any] = {"symbols": {}, "notes": []}
    news: Dict[str, Any] = {"items": [], "notes": []}
    event: Dict[str, Any] = {"window": False, "items": [], "notes": []}
    sentiment: Dict[str, Any] = {"funding": {}, "notes": []}

    ex_cfg = exchange_config if isinstance(exchange_config, dict) else {}
    exchange_id = str(ex_cfg.get("exchange_id") or ex_cfg.get("exchange") or "binance")
    testnet = bool(ex_cfg.get("testnet") or False)

    for sym in symbols[:4]:
        tech_entry: Dict[str, Any] = {"symbol": sym}
        try:
            from app.services.hedge_arb.signals import collect_signals

            s = collect_signals(sym, exchange_id=exchange_id, testnet=testnet)
            tech_entry.update(
                {
                    "funding_rate": s.funding_rate,
                    "basis_pct": s.basis_pct,
                    "spot_price": s.spot_price,
                    "perp_mark_price": s.perp_mark_price,
                    "source": s.source,
                }
            )
            sentiment["funding"][sym] = {
                "funding_rate": s.funding_rate,
                "basis_pct": s.basis_pct,
            }
        except Exception as e:
            technical["notes"].append(f"{sym}: {e}")
            logger.debug("feature funding %s: %s", sym, e)
        technical["symbols"][sym] = tech_entry

    try:
        from app.data_providers import news as news_mod

        for fn_name in ("get_latest_headlines", "fetch_news", "get_news"):
            fn = getattr(news_mod, fn_name, None)
            if callable(fn):
                try:
                    news["items"] = list(fn(limit=8) or [])[:8]
                except TypeError:
                    news["items"] = list(fn() or [])[:8]
                break
    except Exception as e:
        news["notes"].append(str(e))

    try:
        from app.data_providers import economic_calendar as cal_mod

        for fn_name in ("get_upcoming_events", "fetch_calendar", "get_calendar"):
            fn = getattr(cal_mod, fn_name, None)
            if callable(fn):
                try:
                    event["items"] = list(fn(hours=48) or [])[:10]
                except TypeError:
                    event["items"] = list(fn() or [])[:10]
                event["window"] = bool(event["items"])
                break
    except Exception as e:
        event["notes"].append(str(e))

    opportunities: List[Any] = []
    try:
        from app.data_providers import opportunities as opp_mod

        for fn_name in ("scan_opportunities", "get_opportunities"):
            fn = getattr(opp_mod, fn_name, None)
            if callable(fn):
                opportunities = list(fn() or [])[:10]
                break
    except Exception as e:
        technical["notes"].append(f"opportunities: {e}")

    # Serialize dataclass-ish items if any
    clean_opps: List[Any] = []
    for item in opportunities:
        if hasattr(item, "__dataclass_fields__"):
            clean_opps.append(asdict(item))
        elif isinstance(item, dict):
            clean_opps.append(item)
        else:
            clean_opps.append(str(item))

    return {
        "ts": _now_iso(),
        "primary_symbol": primary_symbol,
        "symbols": symbols,
        "dimensions": {
            "technical": technical,
            "news": news,
            "event": event,
            "sentiment": sentiment,
        },
        "opportunities": clean_opps,
        "weights": {"technical": 0.35, "event": 0.25, "news": 0.20, "sentiment": 0.20},
    }
