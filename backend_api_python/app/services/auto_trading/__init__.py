"""AI auto-trading module (PRD): LLM regime JSON + rule engines.

AI never places orders directly. Orchestrator validates regime, applies hard
risk gates, then routes to funding_arb / opportunity / grid engines which
reuse existing QuantDinger execution paths (hedge_arb, notifications, etc.).
"""

from app.services.auto_trading.runner import run_ai_auto_tick

__all__ = ["run_ai_auto_tick"]
