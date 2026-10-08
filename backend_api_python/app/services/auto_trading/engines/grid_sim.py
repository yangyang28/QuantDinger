"""Strategy C — range grid (MVP: simulation / announcement; no flat-add after break)."""
from __future__ import annotations

from typing import Any, Dict

from app.services.auto_trading.config import AiAutoConfig
from app.services.auto_trading.schema import RegimeDecision
from app.utils.strategy_runtime_logs import append_strategy_log


def run_grid_engine(
    strategy_id: int,
    *,
    cfg: AiAutoConfig,
    decision: RegimeDecision,
    execute: bool,
) -> Dict[str, Any]:
    asset_key = cfg.primary_symbol.split("/")[0]
    asset = decision.assets.get(asset_key) or decision.assets.get(asset_key.upper())
    box = (asset.box if asset else None) or []

    plan = {
        "strategy": "GRID_BTC",
        "symbol": cfg.primary_symbol,
        "box": box,
        "spacing_pct_hint": [0.003, 0.008],
        "break_buffer_pct": 0.012,
        "account_fuse_pct": 0.03,
        "sim_only": cfg.grid_sim_only or not execute,
        "rationale_zh": decision.rationale_zh,
    }

    append_strategy_log(
        strategy_id,
        "info",
        f"[ai_auto/grid] RANGE box={box} sim_only={plan['sim_only']} "
        f"(破箱禁止摊平加格)",
    )

    return {
        "engine": "grid",
        "action": "sim_plan" if plan["sim_only"] else "live_deferred",
        "plan": plan,
        "note": "MVP 网格默认仿真；实盘请使用独立 bot_type=grid 或关闭 grid_sim_only",
    }
