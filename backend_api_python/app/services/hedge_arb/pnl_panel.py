"""Client-facing PnL panel payload for hedge_arb strategies.

Aggregates live status, realized trade PnL, funding estimate, and
forward projections (monthly / yearly) for commercial dashboards.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.db import get_db_connection
from app.utils.trade_net_pnl import enrich_trades_net_pnl


# Funding settles ~3 times per day on most crypto perps.
_FUNDINGS_PER_DAY = 3.0
_DAYS_PER_MONTH = 30.0
_DAYS_PER_YEAR = 365.0

_SOURCE_LABELS = {
    "worker": {"zh": "执行引擎成交", "en": "Executor fill"},
    "hedge_enter": {"zh": "开仓双腿", "en": "Hedge enter"},
    "hedge_exit": {"zh": "平仓双腿", "en": "Hedge exit"},
    "hedge_rebalance": {"zh": "再平衡", "en": "Rebalance"},
    "signal_sim": {"zh": "信号模拟", "en": "Signal sim"},
    "grid_poller": {"zh": "网格轮询", "en": "Grid poller"},
    "grid_market": {"zh": "网格市价", "en": "Grid market"},
    "funding": {"zh": "资金费率累计", "en": "Funding accrual"},
    "basis": {"zh": "基差盈亏", "en": "Basis PnL"},
    "fee": {"zh": "手续费", "en": "Fee"},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_ts(value: Any) -> Optional[int]:
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        dt = value
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            if raw.isdigit():
                return int(raw)
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


def _leg_from_market(market_type: str, trade_type: str = "") -> str:
    mt = str(market_type or "").strip().lower()
    if mt in ("spot",):
        return "spot"
    if mt in ("swap", "futures", "future", "perp", "perpetual"):
        return "perp"
    # Heuristic fallback from symbol/type text
    tt = str(trade_type or "").lower()
    if "spot" in tt:
        return "spot"
    return "perp" if mt else "unknown"


def _infer_pnl_source(fill_source: str, net_pnl: float, commission: float) -> str:
    src = str(fill_source or "").strip().lower()
    if "funding" in src:
        return "funding"
    if "rebalance" in src:
        return "rebalance"
    if "enter" in src:
        return "enter"
    if "exit" in src:
        return "exit"
    if abs(float(net_pnl or 0.0)) < 1e-12 and float(commission or 0.0) > 0:
        return "fee"
    return "trade"


def _source_label(fill_source: str, lang: str = "zh") -> str:
    key = str(fill_source or "").strip().lower() or "worker"
    pack = _SOURCE_LABELS.get(key)
    if pack:
        return pack.get(lang) or pack.get("zh") or key
    if not key:
        return "成交" if lang == "zh" else "Fill"
    return key


def project_funding_pnl(
    *,
    funding_rate: float,
    notional_usdt: float,
    hold_ratio: float = 1.0,
) -> Dict[str, float]:
    """Roll forward current funding into monthly / yearly USDT estimates.

    Assumes short-perp receives positive funding when rate > 0.
    hold_ratio scales for partial fill / flat periods (0..1).
    """
    rate = float(funding_rate or 0.0)
    notional = max(float(notional_usdt or 0.0), 0.0)
    ratio = max(0.0, min(float(hold_ratio or 1.0), 1.0))
    per_period = rate * notional * ratio
    daily = per_period * _FUNDINGS_PER_DAY
    monthly = daily * _DAYS_PER_MONTH
    yearly = daily * _DAYS_PER_YEAR
    apr_pct = rate * _FUNDINGS_PER_DAY * _DAYS_PER_YEAR * 100.0
    return {
        "funding_per_period_usdt": round(per_period, 6),
        "estimated_daily_usdt": round(daily, 6),
        "estimated_monthly_usdt": round(monthly, 4),
        "estimated_yearly_usdt": round(yearly, 4),
        "funding_apr_pct": round(apr_pct, 4),
    }


def _fetch_strategy_trades(strategy_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    try:
        from app.services.live_trading.records import ensure_position_ledger_schema

        ensure_position_ledger_schema()
    except Exception:
        pass
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT id, strategy_id, symbol, type, price, amount, value,
                   commission, commission_ccy, profit, close_reason,
                   matched_entry_price, grid_matched_profit,
                   market_type, fill_source, pending_order_id, created_at
            FROM qd_strategy_trades
            WHERE strategy_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(strategy_id), int(limit)),
        )
        rows = cur.fetchall() or []
        cur.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        trade = dict(row)
        ts = _to_ts(trade.get("created_at"))
        if ts is not None:
            trade["created_at"] = ts
        out.append(trade)
    enrich_trades_net_pnl(out)
    return out


def _attribute_trades(trades: List[Dict[str, Any]], *, lang: str = "zh") -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for t in trades:
        net = float(t.get("net_pnl") if t.get("net_pnl") is not None else (t.get("profit") or 0.0))
        commission = float(t.get("commission") or 0.0)
        fill_source = str(t.get("fill_source") or "").strip()
        market_type = str(t.get("market_type") or "").strip().lower()
        leg = _leg_from_market(market_type, str(t.get("type") or ""))
        pnl_source = _infer_pnl_source(fill_source, net, commission)
        items.append(
            {
                "id": t.get("id"),
                "time": t.get("created_at"),
                "symbol": t.get("symbol"),
                "leg": leg,
                "market_type": market_type or ("spot" if leg == "spot" else "swap"),
                "side": str(t.get("type") or ""),
                "price": float(t.get("price") or 0.0),
                "amount": float(t.get("amount") or 0.0),
                "value": float(t.get("value") or 0.0),
                "commission": commission,
                "net_pnl": round(net, 8),
                "fill_source": fill_source or "worker",
                "source_label": _source_label(fill_source, lang=lang),
                "pnl_source": pnl_source,
                "close_reason": str(t.get("close_reason") or ""),
                "pending_order_id": int(t.get("pending_order_id") or 0),
            }
        )
    return items


def build_hedge_arb_pnl_panel(
    *,
    status: Dict[str, Any],
    strategy_id: int,
    strategy_name: str = "",
    initial_capital: float = 0.0,
    lang: str = "zh",
    trade_limit: int = 200,
) -> Dict[str, Any]:
    """Compose the commercial PnL panel JSON from orchestrator status + ledger."""
    lang = "zh" if str(lang or "zh").lower().startswith("zh") else "en"
    perf = status.get("performance") if isinstance(status.get("performance"), dict) else {}
    signals = status.get("signals") if isinstance(status.get("signals"), dict) else {}

    trades_raw = _fetch_strategy_trades(strategy_id, limit=trade_limit)
    attributed = _attribute_trades(trades_raw, lang=lang)

    realized = 0.0
    fees = 0.0
    for row in attributed:
        realized += float(row.get("net_pnl") or 0.0)
        fees += float(row.get("commission") or 0.0)

    unrealized = float(perf.get("unrealized_pnl_usdt") or 0.0)
    funding_est = float(
        status.get("cumulative_funding_est")
        if status.get("cumulative_funding_est") is not None
        else perf.get("cumulative_funding_est") or 0.0
    )
    total_pnl = unrealized + funding_est + realized

    spot_n = float(perf.get("spot_notional_usdt") or 0.0)
    perp_n = float(perf.get("perp_notional_usdt") or 0.0)
    active_notional = max(spot_n, perp_n)
    if active_notional <= 0:
        cfg = status.get("config") if isinstance(status.get("config"), dict) else {}
        active_notional = float(cfg.get("notional_usdt") or 0.0)

    funding_rate = float(signals.get("funding_rate") or 0.0)
    holding = str(status.get("status") or "").lower() in ("holding", "entered", "open")
    hold_ratio = 1.0 if holding and active_notional > 0 else 0.0
    projection = project_funding_pnl(
        funding_rate=funding_rate,
        notional_usdt=active_notional,
        hold_ratio=hold_ratio,
    )

    # Run-rate from realized funding accrual if we have hold duration.
    entered_ts = _to_ts(status.get("entered_at"))
    hold_days = 0.0
    if entered_ts:
        hold_days = max((datetime.now(timezone.utc).timestamp() - entered_ts) / 86400.0, 0.0)
    run_rate_monthly = None
    run_rate_yearly = None
    if hold_days >= 0.25 and abs(funding_est) > 0:
        daily_run = funding_est / hold_days
        run_rate_monthly = round(daily_run * _DAYS_PER_MONTH, 4)
        run_rate_yearly = round(daily_run * _DAYS_PER_YEAR, 4)

    disclaimer_zh = (
        "月/年收益为按当前资金费率与持仓名义的滚动外推，非保证收益；"
        "受费率翻转、基差、滑点与再平衡影响。"
    )
    disclaimer_en = (
        "Monthly/yearly figures are roll-forward estimates from the current funding "
        "rate and notional — not guaranteed. Subject to rate flips, basis, slippage, and rebalance."
    )

    # Synthetic funding attribution row so clients see funding as a PnL source.
    funding_row = {
        "id": "funding-accrual",
        "time": entered_ts or _to_ts(_utc_now_iso()),
        "symbol": status.get("symbol"),
        "leg": "perp",
        "market_type": "swap",
        "side": "funding",
        "price": 0.0,
        "amount": 0.0,
        "value": 0.0,
        "commission": 0.0,
        "net_pnl": round(funding_est, 8),
        "fill_source": "funding",
        "source_label": _source_label("funding", lang=lang),
        "pnl_source": "funding",
        "close_reason": "",
        "pending_order_id": 0,
        "is_synthetic": True,
    }

    ledger_rows = [funding_row] + attributed if abs(funding_est) > 1e-12 else attributed

    return {
        "as_of": _utc_now_iso(),
        "strategy_id": int(strategy_id),
        "strategy_name": strategy_name or "",
        "symbol": status.get("symbol"),
        "exchange_id": status.get("exchange_id"),
        "bot_status": status.get("status"),
        "live_data_ok": bool(status.get("live_data_ok", True)),
        "realtime": {
            "unrealized_pnl_usdt": round(unrealized, 6),
            "realized_pnl_usdt": round(realized, 6),
            "cumulative_funding_est": round(funding_est, 6),
            "total_pnl_usdt": round(total_pnl, 6),
            "fees_paid_usdt": round(fees, 6),
            "spot_notional_usdt": round(spot_n, 4),
            "perp_notional_usdt": round(perp_n, 4),
            "active_notional_usdt": round(active_notional, 4),
            "spot_qty": float(status.get("spot_qty") or 0.0),
            "perp_qty": float(status.get("perp_qty") or 0.0),
            "notional_drift_pct": float(status.get("notional_drift_pct") or 0.0),
            "qty_drift_pct": float(status.get("qty_drift_pct") or 0.0),
            "qty_matched": bool(status.get("qty_matched")),
            "funding_rate": funding_rate,
            "basis_pct": float(signals.get("basis_pct") or 0.0),
            "spot_price": float(signals.get("spot_price") or 0.0),
            "perp_mark_price": float(signals.get("perp_mark_price") or 0.0),
            "entered_at": status.get("entered_at"),
            "hold_days": round(hold_days, 4) if entered_ts else 0.0,
            "initial_capital": float(initial_capital or 0.0),
            "return_on_capital_pct": (
                round(total_pnl / float(initial_capital) * 100.0, 4)
                if float(initial_capital or 0.0) > 0
                else None
            ),
        },
        "projection": {
            "method": "funding_apr_rollforward",
            "is_estimate": True,
            "holding": holding,
            **projection,
            "run_rate_monthly_usdt": run_rate_monthly,
            "run_rate_yearly_usdt": run_rate_yearly,
            "disclaimer": disclaimer_zh if lang == "zh" else disclaimer_en,
        },
        "trades": ledger_rows,
        "trade_count": len(attributed),
        "status_snapshot": {
            "last_error": status.get("last_error"),
            "last_rebalance_at": status.get("last_rebalance_at"),
            "recent_fills": status.get("recent_fills") or [],
            "config": status.get("config") or {},
        },
    }
