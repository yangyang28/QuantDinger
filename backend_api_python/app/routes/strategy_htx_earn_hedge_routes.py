"""HTX earn hedge REST endpoints."""
from __future__ import annotations

import traceback

from flask import g, jsonify, request

from app.routes.strategy_blueprint import strategy_blp
from app.routes.strategy_services import get_strategy_service
from app.services.htx_earn_hedge.orchestrator import HtxEarnHedgeOrchestrator
from app.services.live_trading.base import LiveTradingError
from app.utils.auth import login_required
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _load_strategy(strategy_id: int, user_id: int, *, require_live: bool = False):
    st = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
    if not st:
        return None, jsonify({"code": 0, "msg": "Strategy not found", "data": None}), 404
    tc = st.get("trading_config") if isinstance(st.get("trading_config"), dict) else {}
    bot_type = str(st.get("bot_type") or tc.get("bot_type") or "").strip().lower()
    if bot_type != "htx_earn_hedge":
        return None, jsonify({"code": 0, "msg": "Not a htx_earn_hedge strategy", "data": None}), 400
    if require_live:
        execution_mode = str(st.get("execution_mode") or tc.get("execution_mode") or "signal").strip().lower()
        if execution_mode != "live":
            return None, jsonify({
                "code": 0,
                "msg": "htx_earn_hedge actions require execution_mode=live",
                "data": None,
            }), 400
    return st, None, None


def _orch(st: dict) -> HtxEarnHedgeOrchestrator:
    tc = st.get("trading_config") if isinstance(st.get("trading_config"), dict) else {}
    ex = st.get("exchange_config") if isinstance(st.get("exchange_config"), dict) else {}
    return HtxEarnHedgeOrchestrator(
        strategy_id=int(st.get("id") or 0),
        user_id=int(st.get("user_id") or g.user_id),
        exchange_config=ex,
        trading_config=tc,
    )


@strategy_blp.route("/strategies/htx-earn-hedge/status", methods=["GET"])
@login_required
def htx_earn_hedge_status():
    try:
        strategy_id = request.args.get("id", type=int)
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_strategy(strategy_id, g.user_id)
        if err_resp is not None:
            return err_resp, err_code
        return jsonify({"code": 1, "msg": "success", "data": _orch(st).get_status()})
    except Exception as e:
        logger.error("htx-earn-hedge status: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/htx-earn-hedge/deploy", methods=["POST"])
@login_required
def htx_earn_hedge_deploy():
    try:
        payload = request.get_json(silent=True) or {}
        strategy_id = payload.get("id") or payload.get("strategy_id")
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_strategy(int(strategy_id), g.user_id, require_live=True)
        if err_resp is not None:
            return err_resp, err_code
        data = _orch(st).deploy()
        return jsonify({"code": 1, "msg": "success", "data": data})
    except LiveTradingError as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error("htx-earn-hedge deploy: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/htx-earn-hedge/emergency-exit", methods=["POST"])
@login_required
def htx_earn_hedge_emergency_exit():
    try:
        payload = request.get_json(silent=True) or {}
        strategy_id = payload.get("id") or payload.get("strategy_id")
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_strategy(int(strategy_id), g.user_id, require_live=True)
        if err_resp is not None:
            return err_resp, err_code
        data = _orch(st).emergency_exit()
        return jsonify({"code": 1, "msg": "success", "data": data})
    except LiveTradingError as e:
        return jsonify({"code": 0, "msg": str(e), "data": None}), 400
    except Exception as e:
        logger.error("htx-earn-hedge emergency-exit: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
