"""Persistent state for Binance BTC spot/perp arb strategies."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.utils.db import get_db_connection

FSM_IDLE = "idle"
FSM_ARMED = "ARMED"
FSM_PRE_EXIT = "PRE_EXIT"
FSM_RECONCILING = "RECONCILING"
FSM_DONE = "DONE"

_STATE_DDL = """
CREATE TABLE IF NOT EXISTS qd_binance_btc_arb_state (
    strategy_id INTEGER PRIMARY KEY REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    fsm VARCHAR(32) NOT NULL DEFAULT 'idle',
    symbol VARCHAR(50) NOT NULL DEFAULT '',
    spot_qty DECIMAL(24, 8) NOT NULL DEFAULT 0,
    perp_qty DECIMAL(24, 8) NOT NULL DEFAULT 0,
    last_perp_qty DECIMAL(24, 8) NOT NULL DEFAULT 0,
    deployed_at TIMESTAMP,
    last_error TEXT DEFAULT '',
    extra JSONB DEFAULT '{}'::jsonb,
    pre_exit_done BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_binance_btc_arb_fsm ON qd_binance_btc_arb_state(fsm);
"""


@dataclass
class BinanceBtcArbState:
    strategy_id: int
    fsm: str = FSM_IDLE
    symbol: str = ""
    spot_qty: float = 0.0
    perp_qty: float = 0.0
    last_perp_qty: float = 0.0
    deployed_at: Optional[str] = None
    last_error: str = ""
    extra: Dict[str, Any] = None
    pre_exit_done: bool = False

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}


class BinanceBtcArbStateRepository:
    _schema_ready = False

    @classmethod
    def ensure_schema(cls) -> None:
        if cls._schema_ready:
            return
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(_STATE_DDL)
            cur.close()
        cls._schema_ready = True

    def ensure_row(self, strategy_id: int, symbol: str = "") -> BinanceBtcArbState:
        self.ensure_schema()
        row = self.get(strategy_id)
        if row:
            return row
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_binance_btc_arb_state (strategy_id, symbol, fsm)
                VALUES (%s, %s, %s)
                ON CONFLICT (strategy_id) DO NOTHING
                """,
                (strategy_id, symbol, FSM_IDLE),
            )
            cur.close()
        return self.get(strategy_id) or BinanceBtcArbState(strategy_id=strategy_id, symbol=symbol)

    def get(self, strategy_id: int) -> Optional[BinanceBtcArbState]:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT strategy_id, fsm, symbol, spot_qty, perp_qty, last_perp_qty,
                       deployed_at, last_error, extra, pre_exit_done
                FROM qd_binance_btc_arb_state
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
        return BinanceBtcArbState(
            strategy_id=int(row.get("strategy_id") or strategy_id),
            fsm=str(row.get("fsm") or FSM_IDLE),
            symbol=str(row.get("symbol") or ""),
            spot_qty=float(row.get("spot_qty") or 0),
            perp_qty=float(row.get("perp_qty") or 0),
            last_perp_qty=float(row.get("last_perp_qty") or 0),
            deployed_at=deployed.isoformat() if hasattr(deployed, "isoformat") else (str(deployed) if deployed else None),
            last_error=str(row.get("last_error") or ""),
            extra=extra,
            pre_exit_done=bool(row.get("pre_exit_done")),
        )

    def save(self, state: BinanceBtcArbState) -> None:
        self.ensure_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_binance_btc_arb_state (
                    strategy_id, fsm, symbol, spot_qty, perp_qty, last_perp_qty,
                    deployed_at, last_error, extra, pre_exit_done, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW()
                )
                ON CONFLICT (strategy_id) DO UPDATE SET
                    fsm = EXCLUDED.fsm,
                    symbol = EXCLUDED.symbol,
                    spot_qty = EXCLUDED.spot_qty,
                    perp_qty = EXCLUDED.perp_qty,
                    last_perp_qty = EXCLUDED.last_perp_qty,
                    deployed_at = EXCLUDED.deployed_at,
                    last_error = EXCLUDED.last_error,
                    extra = EXCLUDED.extra,
                    pre_exit_done = EXCLUDED.pre_exit_done,
                    updated_at = NOW()
                """,
                (
                    state.strategy_id,
                    state.fsm,
                    state.symbol,
                    state.spot_qty,
                    state.perp_qty,
                    state.last_perp_qty,
                    state.deployed_at,
                    state.last_error,
                    json.dumps(state.extra or {}),
                    state.pre_exit_done,
                ),
            )
            cur.close()
