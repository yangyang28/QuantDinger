"""
Funding-rate / spot-perp delta-neutral hedge bot ScriptStrategy placeholder.

Live execution is driven by ``app.services.hedge_arb.runner`` (TradingExecutor
tick) and REST ``/api/strategies/hedge-arb/*``. This stub satisfies ScriptStrategy
wiring for create/edit flows.
"""
from __future__ import annotations

FUNDING_ARB_BOT_SCRIPT = r'''
def on_init(ctx):
    ctx.log("hedge_arb: live loop uses funding/basis orchestrator (spot long + perp short)")


def on_bar(ctx, bar):
    # Orchestrator runs server-side; script may log last known params for debugging.
    funding = ctx.params.get("last_funding_rate")
    if funding is not None:
        ctx.log(f"hedge_arb tick close={bar.get('close')} funding={funding}")
'''


def build_funding_arb_bot_script() -> str:
    return FUNDING_ARB_BOT_SCRIPT.strip() + "\n"
