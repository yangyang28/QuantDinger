"""Hedge-arb REST endpoints (enter / exit / rebalance / status)."""
from __future__ import annotations

import traceback

from flask import g, jsonify, request

from app.routes.strategy_blueprint import strategy_blp
from app.routes.strategy_services import get_strategy_service
from app.services.hedge_arb.backtest import simulate_funding_arb
from app.services.hedge_arb.config import parse_hedge_arb_config
from app.services.hedge_arb.orchestrator import HedgeArbOrchestrator
from app.services.live_trading.base import LiveTradingError
from app.utils.auth import login_required
from app.utils.logger import get_logger


logger = get_logger(__name__)


def _load_hedge_strategy(strategy_id: int, user_id: int):
    st = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
    if not st:
        return None, jsonify({"code": 0, "msg": "Strategy not found", "data": None}), 404
    tc = st.get("trading_config") if isinstance(st.get("trading_config"), dict) else {}
    bot_type = str(st.get("bot_type") or tc.get("bot_type") or "").strip().lower()
    if bot_type != "hedge_arb":
        return None, jsonify({"code": 0, "msg": "Not a hedge_arb strategy", "data": None}), 400
    execution_mode = str(st.get("execution_mode") or tc.get("execution_mode") or "signal").strip().lower()
    if execution_mode != "live":
        return None, jsonify({
            "code": 0,
            "msg": "hedge_arb order endpoints require execution_mode=live",
            "data": None,
        }), 400
    return st, None, None


def _orchestrator_for_strategy(st: dict) -> HedgeArbOrchestrator:
    tc = st.get("trading_config") if isinstance(st.get("trading_config"), dict) else {}
    ex = st.get("exchange_config") if isinstance(st.get("exchange_config"), dict) else {}
    return HedgeArbOrchestrator(
        strategy_id=int(st.get("id") or 0),
        user_id=int(st.get("user_id") or g.user_id),
        exchange_config=ex,
        trading_config=tc,
    )


@strategy_blp.route("/strategies/hedge-arb/status", methods=["GET"])
@login_required
def hedge_arb_status():
    try:
        strategy_id = request.args.get("id", type=int)
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st = get_strategy_service().get_strategy(strategy_id, user_id=g.user_id)
        if not st:
            return jsonify({"code": 0, "msg": "Strategy not found", "data": None}), 404
        tc = st.get("trading_config") if isinstance(st.get("trading_config"), dict) else {}
        bot_type = str(st.get("bot_type") or tc.get("bot_type") or "").strip().lower()
        if bot_type != "hedge_arb":
            return jsonify({"code": 0, "msg": "Not a hedge_arb strategy", "data": None}), 400
        data = _orchestrator_for_strategy(st).get_status()
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("hedge-arb status: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/hedge-arb/enter", methods=["POST"])
@login_required
def hedge_arb_enter():
    try:
        payload = request.get_json(silent=True) or {}
        strategy_id = payload.get("id") or payload.get("strategy_id")
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_hedge_strategy(int(strategy_id), g.user_id)
        if err_resp is not None:
            return err_resp, err_code
        notional = payload.get("notional_usdt")
        spot_qty = payload.get("spot_qty")
        perp_qty = payload.get("perp_qty")
        orch = _orchestrator_for_strategy(st)
        result = orch.enter(
            notional_usdt=notional,
            spot_qty=spot_qty,
            perp_qty=perp_qty,
        )
        return jsonify({"code": 1, "msg": "success", "data": result})
    except LiveTradingError as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error("hedge-arb enter: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/hedge-arb/exit", methods=["POST"])
@login_required
def hedge_arb_exit():
    try:
        payload = request.get_json(silent=True) or {}
        strategy_id = payload.get("id") or payload.get("strategy_id")
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_hedge_strategy(int(strategy_id), g.user_id)
        if err_resp is not None:
            return err_resp, err_code
        result = _orchestrator_for_strategy(st).exit()
        return jsonify({"code": 1, "msg": "success", "data": result})
    except LiveTradingError as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error("hedge-arb exit: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/hedge-arb/rebalance", methods=["POST"])
@login_required
def hedge_arb_rebalance():
    try:
        payload = request.get_json(silent=True) or {}
        strategy_id = payload.get("id") or payload.get("strategy_id")
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_hedge_strategy(int(strategy_id), g.user_id)
        if err_resp is not None:
            return err_resp, err_code
        result = _orchestrator_for_strategy(st).rebalance()
        return jsonify({"code": 1, "msg": "success", "data": result})
    except LiveTradingError as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error("hedge-arb rebalance: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/hedge-arb/backtest", methods=["POST"])
@login_required
def hedge_arb_backtest():
    """Approximate funding PnL from Binance historical funding (public API)."""
    try:
        payload = request.get_json(silent=True) or {}
        symbol = str(payload.get("symbol") or "BTC/USDT").strip()
        cfg = parse_hedge_arb_config(payload)
        result = simulate_funding_arb(
            symbol,
            notional_usdt=float(payload.get("notional_usdt") or cfg.notional_usdt),
            entry_funding_rate=float(payload.get("entry_funding_rate") or cfg.entry_funding_rate),
            exit_funding_rate=float(payload.get("exit_funding_rate") or cfg.exit_funding_rate),
            taker_fee_rate=float(payload.get("taker_fee_rate") or 0.0004),
            limit=int(payload.get("limit") or 500),
            testnet=bool(payload.get("testnet")),
        )
        return jsonify({"code": 1, "msg": "success", "data": result})
    except Exception as e:
        logger.error("hedge-arb backtest: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
