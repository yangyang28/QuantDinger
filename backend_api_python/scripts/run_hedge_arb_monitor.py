"""Long-running hedge-arb monitor for testnet / small live validation.

Runs periodic status polls and optional auto-tick via orchestrator logic.
Designed for 24–48h soak tests outside CI.

Usage:
    cd backend_api_python
    set RUN_HEDGE_ARB_MONITOR=1
    set HEDGE_ARB_MONITOR_STRATEGY_ID=123
    python scripts/run_hedge_arb_monitor.py --interval 300 --hours 24
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv_local() -> None:
    path = ROOT / ".env.testnet.local"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def main() -> int:
    parser = argparse.ArgumentParser(description="Hedge-arb soak monitor")
    parser.add_argument("--strategy-id", type=int, default=int(os.getenv("HEDGE_ARB_MONITOR_STRATEGY_ID", "0")))
    parser.add_argument("--interval", type=int, default=300, help="Seconds between ticks")
    parser.add_argument("--hours", type=float, default=24.0, help="Run duration")
    parser.add_argument("--tick", action="store_true", help="Call run_hedge_arb_tick each interval")
    args = parser.parse_args()
    _load_dotenv_local()

    if args.strategy_id <= 0:
        print("Set --strategy-id or HEDGE_ARB_MONITOR_STRATEGY_ID", file=sys.stderr)
        return 2

    from app.services.exchange_execution import load_strategy_configs
    from app.services.hedge_arb.orchestrator import HedgeArbOrchestrator
    from app.services.hedge_arb.runner import run_hedge_arb_tick

    sc = load_strategy_configs(args.strategy_id)
    if not sc:
        print(f"Strategy {args.strategy_id} not found", file=sys.stderr)
        return 1

    end_at = time.time() + max(0.1, args.hours) * 3600.0
    orch = HedgeArbOrchestrator(
        strategy_id=args.strategy_id,
        user_id=int(sc.get("user_id") or 1),
        exchange_config=sc.get("exchange_config") or {},
        trading_config=sc.get("trading_config") or {},
    )

    print(f"Monitoring hedge_arb strategy {args.strategy_id} for {args.hours}h", flush=True)
    while time.time() < end_at:
        status = orch.get_status()
        sig = status.get("signals") or {}
        print(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] status={status.get('status')} "
            f"funding={sig.get('funding_rate')} basis={sig.get('basis_pct')} "
            f"drift={status.get('notional_drift_pct')}",
            flush=True,
        )
        if args.tick:
            run_hedge_arb_tick(
                args.strategy_id,
                user_id=int(sc.get("user_id") or 1),
                exchange_config=sc.get("exchange_config") or {},
                trading_config=sc.get("trading_config") or {},
            )
        time.sleep(max(30, args.interval))

    print("Monitor finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
