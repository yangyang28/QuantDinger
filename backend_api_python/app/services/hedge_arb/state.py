"""Persist hedge-arb runtime state in PostgreSQL."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.utils.db import get_db_connection


@dataclass
class HedgeArbState:
    strategy_id: int
    status: str = "flat"  # flat | holding | error
    symbol: str = ""
    spot_qty: float = 0.0
    perp_qty: float = 0.0
    entry_basis_pct: float = 0.0
    entry_funding_rate: float = 0.0
    cumulative_funding_est: float = 0.0
    entered_at: Optional[str] = None
    last_rebalance_at: Optional[str] = None
    last_error: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HedgeArbStateRepository:
    def get(self, strategy_id: int) -> Optional[HedgeArbState]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT strategy_id, status, symbol, spot_qty, perp_qty,
                       entry_basis_pct, entry_funding_rate, cumulative_funding_est,
                       entered_at, last_rebalance_at, last_error, extra
                FROM qd_hedge_arb_state
                WHERE strategy_id = %s
                """,
                (int(strategy_id),),
            )
            row = cur.fetchone() or {}
            cur.close()
        if not row:
            return None
        extra = row.get("extra")
        if isinstance(extra, str):
            try:
                extra = json.loads(extra) if extra.strip() else {}
            except Exception:
                extra = {}
        if not isinstance(extra, dict):
            extra = {}
        entered = row.get("entered_at")
        rebal = row.get("last_rebalance_at")
        return HedgeArbState(
            strategy_id=int(row.get("strategy_id") or strategy_id),
            status=str(row.get("status") or "flat"),
            symbol=str(row.get("symbol") or ""),
            spot_qty=float(row.get("spot_qty") or 0.0),
            perp_qty=float(row.get("perp_qty") or 0.0),
            entry_basis_pct=float(row.get("entry_basis_pct") or 0.0),
            entry_funding_rate=float(row.get("entry_funding_rate") or 0.0),
            cumulative_funding_est=float(row.get("cumulative_funding_est") or 0.0),
            entered_at=entered.isoformat() if hasattr(entered, "isoformat") else (str(entered) if entered else None),
            last_rebalance_at=rebal.isoformat() if hasattr(rebal, "isoformat") else (str(rebal) if rebal else None),
            last_error=str(row.get("last_error") or ""),
            extra=extra,
        )

    def upsert(self, state: HedgeArbState) -> None:
        extra_json = json.dumps(state.extra or {})
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_hedge_arb_state (
                    strategy_id, status, symbol, spot_qty, perp_qty,
                    entry_basis_pct, entry_funding_rate, cumulative_funding_est,
                    entered_at, last_rebalance_at, last_error, extra, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s::jsonb, NOW()
                )
                ON CONFLICT (strategy_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    symbol = EXCLUDED.symbol,
                    spot_qty = EXCLUDED.spot_qty,
                    perp_qty = EXCLUDED.perp_qty,
                    entry_basis_pct = EXCLUDED.entry_basis_pct,
                    entry_funding_rate = EXCLUDED.entry_funding_rate,
                    cumulative_funding_est = EXCLUDED.cumulative_funding_est,
                    entered_at = EXCLUDED.entered_at,
                    last_rebalance_at = EXCLUDED.last_rebalance_at,
                    last_error = EXCLUDED.last_error,
                    extra = EXCLUDED.extra,
                    updated_at = NOW()
                """,
                (
                    int(state.strategy_id),
                    state.status,
                    state.symbol,
                    state.spot_qty,
                    state.perp_qty,
                    state.entry_basis_pct,
                    state.entry_funding_rate,
                    state.cumulative_funding_est,
                    state.entered_at,
                    state.last_rebalance_at,
                    state.last_error,
                    extra_json,
                ),
            )
            db.commit()
            cur.close()

    def ensure_row(self, strategy_id: int, symbol: str) -> HedgeArbState:
        existing = self.get(strategy_id)
        if existing:
            return existing
        state = HedgeArbState(strategy_id=int(strategy_id), symbol=symbol, status="flat")
        self.upsert(state)
        return state


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
