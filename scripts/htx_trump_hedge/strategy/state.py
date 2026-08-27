"""Persistent strategy state."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


FSM_ARMED = "ARMED"
FSM_PRE_REDEEMING = "PRE_REDEEMING"
FSM_PRE_REDEEMED = "PRE_REDEEMED"
FSM_LIQUIDATED_FAST = "LIQUIDATED_FAST"
FSM_LIQUIDATED_FALLBACK = "LIQUIDATED_FALLBACK"
FSM_RECONCILING = "RECONCILING"
FSM_DONE = "DONE"


@dataclass
class StrategyState:
    spot_symbol: str = "trumpusdt"
    swap_symbol: str = "TRUMP-USDT"
    currency: str = "trump"
    spot_account_id: str = ""
    earn_order_id: Optional[int] = None
    earn_qty: float = 0.0
    perp_qty: float = 0.0
    leverage: int = 2
    fsm: str = FSM_ARMED
    pre_redeemed: bool = False
    redeem_sent: bool = False
    redeem_request_id: str = ""
    last_pre_redeem_ts: float = 0.0
    last_perp_qty: float = 0.0
    deployed_at: float = 0.0
    notes: str = ""

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "StrategyState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def new_request_id(prefix: str = "htx") -> str:
    return f"{prefix}-{int(time.time() * 1000)}"
