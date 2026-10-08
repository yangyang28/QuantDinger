"""AI-auto orchestrator: features → regime → risk → engines."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.auto_trading.ai_regime import produce_regime
from app.services.auto_trading.config import AiAutoConfig, parse_ai_auto_config
from app.services.auto_trading.engines.funding_arb import run_funding_arb_engine
from app.services.auto_trading.engines.grid_sim import run_grid_engine
from app.services.auto_trading.engines.opportunity import run_opportunity_engine
from app.services.auto_trading.risk import apply_risk_gates
from app.services.auto_trading.router import build_engine_plan
from app.services.auto_trading.state import AiAutoStateRepository, HedgeStateRepository
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log

logger = get_logger(__name__)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class AiAutoOrchestrator:
    def __init__(
        self,
        *,
        strategy_id: int,
        user_id: int,
        exchange_config: Dict[str, Any],
        trading_config: Dict[str, Any],
    ):
        self.strategy_id = int(strategy_id)
        self.user_id = int(user_id)
        self.exchange_config = exchange_config if isinstance(exchange_config, dict) else {}
        self.trading_config = trading_config if isinstance(trading_config, dict) else {}
        self.cfg: AiAutoConfig = parse_ai_auto_config(self.trading_config)
        self.repo = AiAutoStateRepository()

    def get_status(self) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id)
        hedge = None
        try:
            hedge = HedgeStateRepository().get("BTC_USDT_HEDGE")
        except Exception:
            hedge = None
        return {
            "strategy_id": self.strategy_id,
            "config": self.cfg.to_dict(),
            "state": state.to_dict(),
            "hedge_state": hedge,
        }

    def set_kill_switch(self, enabled: bool) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id)
        state.kill_switch = bool(enabled)
        state.status = "killed" if enabled else "idle"
        if enabled:
            state.regime = "RISK_OFF"
        self.repo.upsert(state)
        append_strategy_log(
            self.strategy_id,
            "warning" if enabled else "info",
            f"[ai_auto] kill_switch={'ON' if enabled else 'OFF'}",
        )
        return state.to_dict()

    def _regime_is_fresh(self, state) -> bool:
        payload = state.last_regime_json or {}
        ts = _parse_iso(payload.get("ts"))
        if not ts:
            return False
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        valid_min = int(payload.get("valid_until_min") or (self.cfg.regime_refresh_sec // 60))
        return age < max(60, valid_min * 60, self.cfg.regime_refresh_sec)

    def tick(self, *, force_regime: bool = False) -> Dict[str, Any]:
        state = self.repo.ensure_row(self.strategy_id)
        # Prefer DB kill switch over config so /kill persists
        if state.kill_switch or self.cfg.kill_switch:
            state.status = "killed"
            state.regime = "RISK_OFF"
            self.repo.upsert(state)
            return {"ok": False, "reason": "kill_switch", "state": state.to_dict()}

        try:
            HedgeStateRepository().ensure_pair(
                "BTC_USDT_HEDGE",
                symbol=self.cfg.primary_symbol if "BTC" in self.cfg.primary_symbol else "BTC/USDT",
            )
        except Exception as e:
            logger.debug("hedge_state ensure: %s", e)

        from app.services.auto_trading.schema import parse_regime_payload

        decision = None
        features: Dict[str, Any] = {}
        if not force_regime and self._regime_is_fresh(state) and state.last_regime_json:
            try:
                decision = parse_regime_payload(state.last_regime_json, source="cached")
            except Exception:
                decision = None

        if decision is None:
            decision, features = produce_regime(
                symbols=self.cfg.symbols,
                primary_symbol=self.cfg.primary_symbol,
                exchange_config=self.exchange_config,
                use_llm=self.cfg.use_llm,
            )
            try:
                self.repo.save_regime_snapshot(
                    self.strategy_id,
                    regime=decision.regime,
                    payload=decision.to_dict(),
                    features=features,
                    source=decision.source,
                )
            except Exception as e:
                logger.warning("save regime snapshot: %s", e)

        gate = apply_risk_gates(decision, self.cfg, daily_loss_pct=0.0)
        if gate.force_risk_off and not gate.ok:
            state.status = "risk_off"
            state.regime = "RISK_OFF"
            state.human_mode = self.cfg.human_mode
            state.last_regime_json = decision.to_dict()
            state.last_plan_json = gate.to_dict()
            state.last_error = gate.reason
            self.repo.upsert(state)
            append_strategy_log(self.strategy_id, "warning", f"[ai_auto] risk gate block: {gate.reason}")
            return {"ok": False, "reason": gate.reason, "regime": decision.to_dict(), "gate": gate.to_dict()}

        allowed = list(gate.filtered_allowed or [])
        plan = build_engine_plan(decision, self.cfg, allowed)

        # observe: no live orders; confirm/auto: funding arb may execute when mode=auto
        live_exec = self.cfg.human_mode == "auto"

        engine_results: Dict[str, Any] = {}
        if plan.run_funding_arb:
            try:
                engine_results["funding_arb"] = run_funding_arb_engine(
                    self.strategy_id,
                    user_id=self.user_id,
                    exchange_config=self.exchange_config,
                    trading_config=self.trading_config,
                    cfg=self.cfg,
                    execute=live_exec,
                )
            except Exception as e:
                logger.warning("funding_arb engine: %s", e)
                engine_results["funding_arb"] = {"error": str(e)}

        if plan.run_opportunity:
            try:
                engine_results["opportunity"] = run_opportunity_engine(
                    self.strategy_id,
                    user_id=self.user_id,
                    cfg=self.cfg,
                    decision=decision,
                    execute=live_exec,
                )
            except Exception as e:
                engine_results["opportunity"] = {"error": str(e)}

        if plan.run_grid:
            try:
                engine_results["grid"] = run_grid_engine(
                    self.strategy_id,
                    cfg=self.cfg,
                    decision=decision,
                    execute=live_exec and not self.cfg.grid_sim_only,
                )
            except Exception as e:
                engine_results["grid"] = {"error": str(e)}

        state.status = "running"
        state.regime = decision.regime
        state.human_mode = self.cfg.human_mode
        state.last_regime_json = decision.to_dict()
        state.last_plan_json = {"plan": plan.to_dict(), "gate": gate.to_dict(), "engines": engine_results}
        state.last_error = ""
        self.repo.upsert(state)

        append_strategy_log(
            self.strategy_id,
            "info",
            f"[ai_auto] regime={decision.regime} shock={decision.event_shock} "
            f"mode={self.cfg.human_mode} plan={plan.to_dict()} | {decision.rationale_zh}",
        )

        return {
            "ok": True,
            "regime": decision.to_dict(),
            "gate": gate.to_dict(),
            "plan": plan.to_dict(),
            "engines": engine_results,
            "state": state.to_dict(),
        }
