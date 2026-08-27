#!/usr/bin/env python3
"""
HTX TRUMP hedge bot (standalone).

100%% earn stake, no stop-loss; pre-redeem near liquidation; sell spot on forced liquidation.

Usage:
  python main.py deploy --config config.yaml
  python main.py run --config config.yaml
  python main.py status --config config.yaml
  python main.py emergency-exit --config config.yaml
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from htx.rest import HtxClient
from strategy.deploy import deploy
from strategy.exit_fsm import emergency_exit, run_loop
from strategy.reconcile import is_flat
from strategy.state import StrategyState


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_client(cfg: dict) -> HtxClient:
    htx = cfg.get("htx") or {}
    api_key = os.environ.get(htx.get("api_key_env") or "HTX_API_KEY", "")
    secret = os.environ.get(htx.get("secret_env") or "HTX_API_SECRET", "")
    if not api_key or not secret:
        raise SystemExit("Set HTX_API_KEY and HTX_API_SECRET in environment or .env")
    return HtxClient(
        api_key=api_key,
        secret_key=secret,
        spot_base=htx.get("spot_base") or "https://api.htx.com",
        swap_base=htx.get("swap_base") or "https://api.hbdm.com",
    )


def state_path(cfg: dict) -> Path:
    sf = (cfg.get("safety") or {}).get("state_file") or "state.json"
    p = Path(sf)
    return p if p.is_absolute() else ROOT / p


def cmd_deploy(cfg: dict) -> None:
    client = build_client(cfg)
    try:
        if not client.ping():
            raise SystemExit("HTX API ping failed")
        st = StrategyState.load(state_path(cfg))
        deploy(client, cfg, st, state_path(cfg))
        print("Deploy OK. Run: python main.py run --config config.yaml")
    finally:
        client.close()


def cmd_run(cfg: dict) -> None:
    client = build_client(cfg)
    try:
        st = StrategyState.load(state_path(cfg))
        if st.deployed_at <= 0:
            raise SystemExit("Not deployed. Run deploy first.")
        run_loop(client, st, cfg, state_path(cfg))
    finally:
        client.close()


def cmd_status(cfg: dict) -> None:
    client = build_client(cfg)
    try:
        st = StrategyState.load(state_path(cfg))
        strat = cfg.get("strategy") or {}
        currency = (strat.get("currency") or st.currency or "trump").lower()
        swap = strat.get("swap_symbol") or st.swap_symbol
        _, spot = client.get_spot_balance(currency)
        earn, oid = client.earn_total_qty(currency)
        perp = client.swap_short_volume(swap)
        mark = client.swap_ticker(swap)
        liq = client.swap_liquidation_price(swap)
        flat = is_flat(client, st, float((cfg.get("safety") or {}).get("min_sell_qty") or 0.01))
        print("--- state ---")
        print(f"fsm:           {st.fsm}")
        print(f"pre_redeemed:  {st.pre_redeemed}")
        print(f"earn_order_id: {st.earn_order_id or oid}")
        print(f"earn_qty:      {earn:.8f}")
        print(f"spot_avail:    {spot:.8f}")
        print(f"perp_short:    {perp:.8f}")
        print(f"mark:          {mark:.6f}")
        print(f"liq_price:     {liq:.6f}")
        if liq > 0 and mark > 0:
            dist = (liq - mark) / liq
            print(f"dist_to_liq:   {dist * 100:.3f}%")
        print(f"flat:          {flat}")
    finally:
        client.close()


def cmd_emergency(cfg: dict) -> None:
    client = build_client(cfg)
    try:
        st = StrategyState.load(state_path(cfg))
        emergency_exit(client, st, cfg, state_path(cfg))
        print("Emergency exit finished (see logs / status)")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="HTX TRUMP earn + short hedge bot")
    parser.add_argument("command", choices=["deploy", "run", "status", "emergency-exit"])
    parser.add_argument("--config", default="config.yaml", help="path to config yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    load_dotenv(ROOT / ".env")

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    if not cfg_path.exists():
        raise SystemExit(f"Config not found: {cfg_path}. Copy config.example.yaml to config.yaml")

    cfg = load_config(cfg_path)
    cmds = {
        "deploy": cmd_deploy,
        "run": cmd_run,
        "status": cmd_status,
        "emergency-exit": cmd_emergency,
    }
    cmds[args.command](cfg)


if __name__ == "__main__":
    main()
