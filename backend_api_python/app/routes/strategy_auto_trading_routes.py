"""AI auto-trading REST endpoints (status / tick / kill / refresh regime)."""
from __future__ import annotations

import traceback

from flask import g, jsonify, request

from app.routes.strategy_blueprint import strategy_blp
from app.routes.strategy_services import get_strategy_service
from app.services.auto_trading.orchestrator import AiAutoOrchestrator
from app.utils.auth import login_required
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _load_ai_auto_strategy(strategy_id: int, user_id: int):
    st = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
    if not st:
        return None, jsonify({"code": 0, "msg": "Strategy not found", "data": None}), 404
    tc = st.get("trading_config") if isinstance(st.get("trading_config"), dict) else {}
    bot_type = str(st.get("bot_type") or tc.get("bot_type") or "").strip().lower()
    if bot_type != "ai_auto":
        return None, jsonify({"code": 0, "msg": "Not an ai_auto strategy", "data": None}), 400
    return st, None, None


def _orch(st: dict) -> AiAutoOrchestrator:
    tc = st.get("trading_config") if isinstance(st.get("trading_config"), dict) else {}
    ex = st.get("exchange_config") if isinstance(st.get("exchange_config"), dict) else {}
    return AiAutoOrchestrator(
        strategy_id=int(st.get("id") or 0),
        user_id=int(st.get("user_id") or g.user_id),
        exchange_config=ex,
        trading_config=tc,
    )


@strategy_blp.route("/strategies/ai-auto/status", methods=["GET"])
@login_required
def ai_auto_status():
    try:
        strategy_id = request.args.get("id", type=int)
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_ai_auto_strategy(strategy_id, g.user_id)
        if err_resp is not None:
            return err_resp, err_code
        return jsonify({"code": 1, "msg": "success", "data": _orch(st).get_status()})
    except Exception as e:
        logger.error("ai-auto status: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/ai-auto/tick", methods=["POST"])
@login_required
def ai_auto_tick():
    try:
        payload = request.get_json(silent=True) or {}
        strategy_id = payload.get("id") or payload.get("strategy_id")
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_ai_auto_strategy(int(strategy_id), g.user_id)
        if err_resp is not None:
            return err_resp, err_code
        force = bool(payload.get("force_regime") or payload.get("force"))
        data = _orch(st).tick(force_regime=force)
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("ai-auto tick: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@strategy_blp.route("/strategies/ai-auto/kill", methods=["POST"])
@login_required
def ai_auto_kill():
    try:
        payload = request.get_json(silent=True) or {}
        strategy_id = payload.get("id") or payload.get("strategy_id")
        if not strategy_id:
            return jsonify({"code": 0, "msg": "Missing strategy id", "data": None}), 400
        st, err_resp, err_code = _load_ai_auto_strategy(int(strategy_id), g.user_id)
        if err_resp is not None:
            return err_resp, err_code
        enabled = payload.get("enabled")
        if enabled is None:
            enabled = True
        data = _orch(st).set_kill_switch(bool(enabled))
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as e:
        logger.error("ai-auto kill: %s\n%s", e, traceback.format_exc())
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
