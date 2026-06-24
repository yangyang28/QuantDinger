#!/usr/bin/env python3
"""
Verify hedge-arb module: unit tests + optional Binance testnet dual-leg smoke.

Usage:
    cd backend_api_python
    python scripts/verify_hedge_arb_testnet.py
    python scripts/verify_hedge_arb_testnet.py --live
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def _run_pytest(extra: list[str]) -> int:
    cmd = [sys.executable, "-m", "pytest", *extra]
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify hedge-arb tests")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run optional Binance testnet integration (needs .env.testnet.local)",
    )
    args = parser.parse_args()
    _load_dotenv_local()

    code = _run_pytest(["tests/test_hedge_arb.py", "-v"])
    if code != 0:
        return code

    if args.live:
        os.environ.setdefault("RUN_HEDGE_ARB_LIVE_TESTS", "1")
        code = _run_pytest(["tests/test_hedge_arb_live.py", "-m", "integration", "-v"])
        if code != 0:
            return code
        print("\nHedge-arb live smoke passed.", flush=True)
    else:
        print(
            "\nUnit tests passed. Optional testnet smoke: "
            "python scripts/verify_hedge_arb_testnet.py --live",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
