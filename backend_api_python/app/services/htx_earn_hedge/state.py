"""Persistent state for HTX earn hedge strategies."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.utils.db import get_db_connection

FSM_IDLE = "idle"
FSM_ARMED = "ARMED"
FSM_PRE_REDEEMING = "PRE_REDEEMING"
FSM_PRE_REDEEMED = "PRE_REDEEMED"
FSM_RECONCILING = "RECONCILING"
FSM_DONE = "DONE"


@dataclass
class HtxEarnHedgeState:
    strategy_id: int
    fsm: str = FSM_IDLE
    symbol: str = ""
    currency: str = ""
    earn_order_id: Optional[int] = None
    earn_qty: float = 0.0
    perp_qty: float = 0.0
    pre_redeemed: bool = False
    redeem_sent: bool = False
    redeem_request_id: str = ""
    last_perp_qty: float = 0.0
    deployed_at: Optional[str] = None
    last_error: str = ""
    extra: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}


class HtxEarnHedgeStateRepository:
    def ensure_row(self, strategy_id: int, symbol: str = "") -> HtxEarnHedgeState:
        row = self.get(strategy_id)
        if row:
            return row
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_htx_earn_hedge_state (strategy_id, symbol, fsm)
                VALUES (%s, %s, %s)
                ON CONFLICT (strategy_id) DO NOTHING
                """,
                (strategy_id, symbol, FSM_IDLE),
            )
            cur.close()
        return self.get(strategy_id) or HtxEarnHedgeState(strategy_id=strategy_id, symbol=symbol)

    def get(self, strategy_id: int) -> Optional[HtxEarnHedgeState]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT strategy_id, fsm, symbol, currency, earn_order_id, earn_qty, perp_qty,
                       pre_redeemed, redeem_sent, redeem_request_id, last_perp_qty,
                       deployed_at, last_error, extra
                FROM qd_htx_earn_hedge_state
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
        deployed = row.get("deployed_at")
        earn_oid = row.get("earn_order_id")
        return HtxEarnHedgeState(
            strategy_id=int(row.get("strategy_id") or strategy_id),
            fsm=str(row.get("fsm") or FSM_IDLE),
            symbol=str(row.get("symbol") or ""),
            currency=str(row.get("currency") or ""),
            earn_order_id=int(earn_oid) if earn_oid is not None else None,
            earn_qty=float(row.get("earn_qty") or 0),
            perp_qty=float(row.get("perp_qty") or 0),
            pre_redeemed=bool(row.get("pre_redeemed")),
            redeem_sent=bool(row.get("redeem_sent")),
            redeem_request_id=str(row.get("redeem_request_id") or ""),
            last_perp_qty=float(row.get("last_perp_qty") or 0),
            deployed_at=deployed.isoformat() if hasattr(deployed, "isoformat") else (str(deployed) if deployed else None),
            last_error=str(row.get("last_error") or ""),
            extra=extra,
        )

    def save(self, state: HtxEarnHedgeState) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_htx_earn_hedge_state (
                    strategy_id, fsm, symbol, currency, earn_order_id, earn_qty, perp_qty,
                    pre_redeemed, redeem_sent, redeem_request_id, last_perp_qty,
                    deployed_at, last_error, extra, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW()
                )
                ON CONFLICT (strategy_id) DO UPDATE SET
                    fsm = EXCLUDED.fsm,
                    symbol = EXCLUDED.symbol,
                    currency = EXCLUDED.currency,
                    earn_order_id = EXCLUDED.earn_order_id,
                    earn_qty = EXCLUDED.earn_qty,
                    perp_qty = EXCLUDED.perp_qty,
                    pre_redeemed = EXCLUDED.pre_redeemed,
                    redeem_sent = EXCLUDED.redeem_sent,
                    redeem_request_id = EXCLUDED.redeem_request_id,
                    last_perp_qty = EXCLUDED.last_perp_qty,
                    deployed_at = EXCLUDED.deployed_at,
                    last_error = EXCLUDED.last_error,
                    extra = EXCLUDED.extra,
                    updated_at = NOW()
                """,
                (
                    state.strategy_id,
                    state.fsm,
                    state.symbol,
                    state.currency,
                    state.earn_order_id,
                    state.earn_qty,
                    state.perp_qty,
                    state.pre_redeemed,
                    state.redeem_sent,
                    state.redeem_request_id,
                    state.last_perp_qty,
                    state.deployed_at,
                    state.last_error,
                    json.dumps(state.extra or {}),
                ),
            )
            cur.close()
