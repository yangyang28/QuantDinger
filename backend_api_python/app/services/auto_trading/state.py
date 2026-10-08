"""Persist AI-auto runtime state and regime snapshots."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from app.utils.db import get_db_connection


@dataclass
class AiAutoState:
    strategy_id: int
    status: str = "idle"  # idle | running | risk_off | killed | error
    regime: str = "RISK_OFF"
    human_mode: str = "observe"
    last_regime_json: Dict[str, Any] = field(default_factory=dict)
    last_plan_json: Dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    kill_switch: bool = False
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AiAutoStateRepository:
    def ensure_row(self, strategy_id: int) -> AiAutoState:
        existing = self.get(strategy_id)
        if existing:
            return existing
        state = AiAutoState(strategy_id=int(strategy_id))
        self.upsert(state)
        return state

    def get(self, strategy_id: int) -> Optional[AiAutoState]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT strategy_id, status, regime, human_mode,
                       last_regime_json, last_plan_json, last_error, kill_switch, updated_at
                FROM qd_ai_auto_state
                WHERE strategy_id = %s
                """,
                (int(strategy_id),),
            )
            row = cur.fetchone() or {}
            cur.close()
        if not row:
            return None
        return self._row_to_state(row, strategy_id)

    def upsert(self, state: AiAutoState) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_ai_auto_state (
                    strategy_id, status, regime, human_mode,
                    last_regime_json, last_plan_json, last_error, kill_switch, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s, %s, NOW()
                )
                ON CONFLICT (strategy_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    regime = EXCLUDED.regime,
                    human_mode = EXCLUDED.human_mode,
                    last_regime_json = EXCLUDED.last_regime_json,
                    last_plan_json = EXCLUDED.last_plan_json,
                    last_error = EXCLUDED.last_error,
                    kill_switch = EXCLUDED.kill_switch,
                    updated_at = NOW()
                """,
                (
                    int(state.strategy_id),
                    state.status,
                    state.regime,
                    state.human_mode,
                    json.dumps(state.last_regime_json or {}),
                    json.dumps(state.last_plan_json or {}),
                    state.last_error or "",
                    bool(state.kill_switch),
                ),
            )
            db.commit()
            cur.close()

    def save_regime_snapshot(
        self,
        strategy_id: int,
        *,
        regime: str,
        payload: Dict[str, Any],
        features: Optional[Dict[str, Any]] = None,
        source: str = "llm",
    ) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_ai_auto_regime_snapshots (
                    strategy_id, regime, source, payload, features, created_at
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW())
                """,
                (
                    int(strategy_id),
                    str(regime),
                    str(source),
                    json.dumps(payload or {}),
                    json.dumps(features or {}),
                ),
            )
            db.commit()
            cur.close()

    @staticmethod
    def _row_to_state(row: Dict[str, Any], strategy_id: int) -> AiAutoState:
        def _json_col(v: Any) -> Dict[str, Any]:
            if isinstance(v, dict):
                return v
            if isinstance(v, str) and v.strip():
                try:
                    obj = json.loads(v)
                    return obj if isinstance(obj, dict) else {}
                except Exception:
                    return {}
            return {}

        updated = row.get("updated_at")
        return AiAutoState(
            strategy_id=int(row.get("strategy_id") or strategy_id),
            status=str(row.get("status") or "idle"),
            regime=str(row.get("regime") or "RISK_OFF"),
            human_mode=str(row.get("human_mode") or "observe"),
            last_regime_json=_json_col(row.get("last_regime_json")),
            last_plan_json=_json_col(row.get("last_plan_json")),
            last_error=str(row.get("last_error") or ""),
            kill_switch=bool(row.get("kill_switch")),
            updated_at=updated.isoformat() if hasattr(updated, "isoformat") else (str(updated) if updated else None),
        )


class HedgeStateRepository:
    """Legacy/compat hedge_state table (pair-level FSM) from ops SQL."""

    def ensure_pair(self, pair_id: str = "BTC_USDT_HEDGE", *, symbol: str = "BTC/USDT") -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO hedge_state (pair_id, symbol)
                VALUES (%s, %s)
                ON CONFLICT (pair_id) DO NOTHING
                """,
                (pair_id, symbol),
            )
            db.commit()
            cur.close()

    def get(self, pair_id: str = "BTC_USDT_HEDGE") -> Optional[Dict[str, Any]]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("SELECT * FROM hedge_state WHERE pair_id = %s", (pair_id,))
            row = cur.fetchone()
            cur.close()
        return dict(row) if row else None
