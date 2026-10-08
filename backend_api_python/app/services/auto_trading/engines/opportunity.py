"""Strategy B — opportunity signals (MVP: notify / confirm; no naked LLM orders)."""
from __future__ import annotations

from typing import Any, Dict

from app.services.auto_trading.config import AiAutoConfig
from app.services.auto_trading.schema import RegimeDecision
from app.utils.strategy_runtime_logs import append_strategy_log


def run_opportunity_engine(
    strategy_id: int,
    *,
    user_id: int,
    cfg: AiAutoConfig,
    decision: RegimeDecision,
    execute: bool,
) -> Dict[str, Any]:
    asset_key = cfg.primary_symbol.split("/")[0]
    asset = decision.assets.get(asset_key) or decision.assets.get(asset_key.upper())
    bias = asset.bias if asset else "neutral"
    conf = asset.confidence if asset else 0.0
    box = asset.box if asset else None

    card = {
        "strategy": "OPP_TREND",
        "symbol": cfg.primary_symbol,
        "bias": bias,
        "confidence": conf,
        "box": box,
        "risk_pct": cfg.opportunity_risk_pct,
        "stop_loss_hint_pct": 0.02,
        "take_profit_hint_pct": 0.04,
        "rationale_zh": decision.rationale_zh,
        "mode": cfg.human_mode,
        "user_id": user_id,
    }

    append_strategy_log(
        strategy_id,
        "info",
        f"[ai_auto/opp] {cfg.primary_symbol} bias={bias} conf={conf:.2f} "
        f"mode={cfg.human_mode} execute={execute}",
    )

    notified = False
    try:
        from app.services.signal_notifier import SignalNotifier

        SignalNotifier().notify_signal(
            strategy_id=int(strategy_id),
            strategy_name="ai_auto",
            symbol=cfg.primary_symbol,
            signal_type=f"AI_OPP_{bias.upper()}",
            price=0.0,
            direction="long" if bias == "bull" else ("short" if bias == "bear" else "long"),
            extra=card,
        )
        notified = True
    except Exception:
        notified = False

    return {
        "engine": "opportunity",
        "action": "signal",
        "card": card,
        "notified": notified,
        "note": "MVP 不自动开机会单；confirm/auto 仅推送信号卡，成交须经规则引擎",
    }
