"""HTX REST client: spot, linear swap V5, earn."""

from __future__ import annotations

import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from htx.auth import sign_params

logger = logging.getLogger(__name__)


class HtxError(Exception):
    pass


def _v5_ok(raw: dict) -> bool:
    if str(raw.get("status") or "").lower() == "ok":
        return True
    try:
        return int(raw.get("code") or 0) == 200
    except (TypeError, ValueError):
        return False


def _v5_data(raw: dict) -> Any:
    return raw.get("data")


class HtxClient:
    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        spot_base: str = "https://api.htx.com",
        swap_base: str = "https://api.hbdm.com",
        timeout: float = 10.0,
    ):
        self.api_key = (api_key or "").strip()
        self.secret_key = (secret_key or "").strip()
        self.spot_base = spot_base.rstrip("/")
        self.swap_base = swap_base.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        self._spot_account_id: Optional[str] = None

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict:
        resp = self._client.request(method, url, params=params, json=json_body)
        text = resp.text
        if resp.status_code >= 400:
            raise HtxError(f"HTTP {resp.status_code}: {text[:500]}")
        try:
            data = resp.json()
        except Exception as exc:
            raise HtxError(f"Invalid JSON: {text[:200]}") from exc
        if isinstance(data, dict) and str(data.get("status") or "").lower() == "error":
            raise HtxError(str(data.get("err-msg") or data.get("err_msg") or data))
        return data if isinstance(data, dict) else {"raw": data}

    def _spot_private(self, method: str, path: str, *, params: Optional[dict] = None, json_body: Optional[dict] = None) -> dict:
        signed = sign_params(
            method=method,
            base_url=self.spot_base,
            path=path,
            params=params or {},
            api_key=self.api_key,
            secret_key=self.secret_key,
        )
        url = f"{self.spot_base}{path}"
        if method.upper() == "GET":
            return self._request("GET", url, params=signed)
        return self._request(method, f"{url}?{urlencode(sorted((str(k), str(v)) for k, v in signed.items()))}", json_body=json_body)

    def _spot_public(self, path: str, *, params: Optional[dict] = None) -> dict:
        return self._request("GET", f"{self.spot_base}{path}", params=params)

    def _swap_private(self, method: str, path: str, *, params: Optional[dict] = None, json_body: Optional[dict] = None) -> dict:
        signed = sign_params(
            method=method,
            base_url=self.swap_base,
            path=path,
            params=params or {},
            api_key=self.api_key,
            secret_key=self.secret_key,
        )
        url = f"{self.swap_base}{path}"
        if method.upper() == "GET":
            raw = self._request("GET", url, params=signed)
        else:
            raw = self._request(method, f"{url}?{urlencode(sorted((str(k), str(v)) for k, v in signed.items()))}", json_body=json_body)
        if not _v5_ok(raw):
            raise HtxError(str(raw.get("err_msg") or raw.get("msg") or raw))
        return raw

    def _swap_public(self, path: str, *, params: Optional[dict] = None) -> dict:
        return self._request("GET", f"{self.swap_base}{path}", params=params)

    # --- spot ---

    def get_spot_account_id(self) -> str:
        if self._spot_account_id:
            return self._spot_account_id
        raw = self._spot_private("GET", "/v1/account/accounts")
        for item in raw.get("data") or []:
            if isinstance(item, dict) and str(item.get("type") or "") == "spot" and item.get("id"):
                self._spot_account_id = str(item["id"])
                return self._spot_account_id
        for item in raw.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                self._spot_account_id = str(item["id"])
                return self._spot_account_id
        raise HtxError("spot account id not found")

    def get_spot_balance(self, currency: str) -> tuple[float, float]:
        """Return (total, available) for currency in spot trade account."""
        account_id = self.get_spot_account_id()
        raw = self._spot_private("GET", f"/v1/account/accounts/{account_id}/balance")
        ccy = currency.lower()
        total = avail = 0.0
        for item in (raw.get("data") or {}).get("list") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("currency") or "").lower() != ccy:
                continue
            if str(item.get("type") or "") == "trade":
                avail = float(item.get("balance") or 0)
            total += float(item.get("balance") or 0)
        return total, avail

    def spot_ticker(self, symbol: str) -> float:
        raw = self._spot_public("/market/detail/merged", params={"symbol": symbol.lower()})
        tick = raw.get("tick") or {}
        return float(tick.get("close") or tick.get("bid") or 0)

    def spot_market_buy_usdt(self, symbol: str, usdt_amount: float, client_order_id: str = "") -> str:
        account_id = self.get_spot_account_id()
        body: dict[str, Any] = {
            "account-id": account_id,
            "symbol": symbol.lower(),
            "type": "buy-market",
            "amount": f"{usdt_amount:.8f}".rstrip("0").rstrip("."),
            "source": "spot-api",
        }
        if client_order_id:
            body["client-order-id"] = client_order_id[:64]
        raw = self._spot_private("POST", "/v1/order/orders/place", json_body=body)
        return str(raw.get("data") or "")

    def spot_market_sell(self, symbol: str, amount: float, client_order_id: str = "") -> str:
        account_id = self.get_spot_account_id()
        body: dict[str, Any] = {
            "account-id": account_id,
            "symbol": symbol.lower(),
            "type": "sell-market",
            "amount": f"{amount:.8f}".rstrip("0").rstrip("."),
            "source": "spot-api",
        }
        if client_order_id:
            body["client-order-id"] = client_order_id[:64]
        raw = self._spot_private("POST", "/v1/order/orders/place", json_body=body)
        return str(raw.get("data") or "")

    # --- earn ---

    def earn_find_flexible_project(self, currency: str) -> dict:
        raw = self._spot_private(
            "GET",
            "/v1/earn/project/queryEarnProjectList",
            params={"currency": currency.upper(), "projectType": "0", "pageNum": "1", "pageSize": "20"},
        )
        items = (raw.get("data") or {}).get("items") or raw.get("data") or []
        if isinstance(items, dict):
            items = items.get("items") or []
        for item in items:
            if isinstance(item, dict):
                return item
        raise HtxError(f"no flexible earn project for {currency}")

    def earn_user_assets(self, currency: str) -> list[dict]:
        raw = self._spot_private(
            "GET",
            "/v1/earn/order/user/assets/list",
            params={"projectType": "0", "currency": currency.upper(), "pageNum": "1", "pageSize": "100"},
        )
        data = raw.get("data") or {}
        items = data.get("items") if isinstance(data, dict) else data
        return [x for x in (items or []) if isinstance(x, dict)]

    def earn_subscribe(self, project_id: int, amount: str, request_id: str) -> dict:
        body = {"id": int(project_id), "amount": str(amount), "requestId": request_id}
        return self._spot_private("POST", "/v1/earn/order/demand/add", json_body=body)

    def earn_redeem(self, order_id: int, amount: str, request_id: str) -> dict:
        body = {"orderId": int(order_id), "amount": str(amount), "requestId": request_id}
        return self._spot_private("POST", "/v1/earn/order/demand/redeem-order", json_body=body)

    def earn_total_qty(self, currency: str) -> tuple[float, Optional[int]]:
        """Return (total_qty, primary_order_id)."""
        assets = self.earn_user_assets(currency)
        total = 0.0
        order_id = None
        for row in assets:
            amt = float(row.get("amount") or row.get("totalAmount") or row.get("balance") or 0)
            total += amt
            if order_id is None and row.get("orderId"):
                order_id = int(row["orderId"])
        return total, order_id

    # --- swap ---

    def swap_ticker(self, contract_code: str) -> float:
        raw = self._swap_public("/linear-swap-ex/market/detail/merged", params={"contract_code": contract_code})
        tick = raw.get("tick") or {}
        return float(tick.get("close") or 0)

    def swap_contract_size(self, contract_code: str) -> float:
        raw = self._swap_public("/linear-swap-api/v1/swap_contract_info", params={"contract_code": contract_code})
        data = raw.get("data") or []
        if data and isinstance(data[0], dict):
            return float(data[0].get("contract_size") or 1)
        return 1.0

    def qty_to_contracts(self, contract_code: str, base_qty: float) -> int:
        size = self.swap_contract_size(contract_code)
        if size <= 0:
            size = 1.0
        n = int((Decimal(str(base_qty)) / Decimal(str(size))).to_integral_value(rounding=ROUND_DOWN))
        return max(n, 1)

    def swap_set_leverage(self, contract_code: str, leverage: int) -> None:
        body = {
            "contract_code": contract_code,
            "lever_rate": int(leverage),
            "margin_mode": "cross",
        }
        self._swap_private("POST", "/v5/position/lever", json_body=body)

    def swap_get_positions(self, contract_code: str) -> list[dict]:
        try:
            raw = self._swap_private("GET", "/v5/trade/position/opens", params={"contract_code": contract_code})
        except HtxError:
            raw = self._swap_private("POST", "/v5/trade/position_all", json_body={"contract_code": contract_code})
        data = _v5_data(raw)
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict)]
        if isinstance(data, dict):
            for key in ("positions", "list", "data"):
                nested = data.get(key)
                if isinstance(nested, list):
                    return [p for p in nested if isinstance(p, dict)]
            if data.get("contract_code"):
                return [data]
        return []

    def _is_short_position(self, pos: dict) -> bool:
        direction = str(pos.get("direction") or pos.get("side") or "").lower()
        position_side = str(pos.get("position_side") or pos.get("positionSide") or "").lower()
        if position_side == "short":
            return True
        if position_side == "long":
            return False
        return direction in ("sell", "short")

    def swap_short_volume(self, contract_code: str) -> float:
        """Return absolute base qty of open short."""
        total = 0.0
        size = self.swap_contract_size(contract_code)
        for pos in self.swap_get_positions(contract_code):
            if not self._is_short_position(pos):
                continue
            vol = float(pos.get("volume") or pos.get("qty") or pos.get("position_qty") or 0)
            if vol <= 0:
                continue
            # HTX V5 may return contracts in volume; if value looks like contracts, scale.
            if vol < 1e6 and float(pos.get("contract_size") or 0) > 0:
                total += vol * float(pos["contract_size"])
            elif size > 0 and vol == int(vol):
                total += vol * size
            else:
                total += vol
        return total

    def swap_liquidation_price(self, contract_code: str) -> float:
        for pos in self.swap_get_positions(contract_code):
            if not self._is_short_position(pos):
                continue
            for key in (
                "liquidation_price",
                "liq_price",
                "liquidationPrice",
                "liq_px",
                "estimate_liquidation_price",
                "est_liq_price",
            ):
                val = pos.get(key)
                if val is not None:
                    try:
                        px = float(val)
                        if px > 0:
                            return px
                    except (TypeError, ValueError):
                        pass
            entry = float(
                pos.get("cost_open")
                or pos.get("avg_open_price")
                or pos.get("open_avg_price")
                or pos.get("open_avg_px")
                or pos.get("last_price")
                or 0
            )
            lever = float(pos.get("lever_rate") or pos.get("lever") or 2)
            if entry > 0 and lever > 0:
                return entry * (1.0 + 1.0 / lever)
        return 0.0

    def _swap_hedge_mode(self, contract_code: str) -> bool:
        for params in (
            {"contract_code": contract_code, "margin_mode": "cross"},
            {"contract_code": contract_code},
        ):
            try:
                raw = self._swap_private("GET", "/v5/position/mode", params=params)
                data = _v5_data(raw)
                if isinstance(data, dict):
                    mode = str(data.get("position_mode") or data.get("positionMode") or "").lower()
                    if mode in ("dual_side", "dual", "hedge", "hedged"):
                        return True
                    if mode in ("single_side", "single", "oneway", "one_way", "one-way"):
                        return False
            except HtxError:
                continue
        return False

    def _build_v5_order_body(
        self,
        *,
        contract_code: str,
        volume: int,
        side: str,
        reduce_only: bool,
        position_side: str,
        client_order_id: str = "",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "contract_code": contract_code,
            "volume": int(volume),
            "side": side.lower(),
            "type": "market",
            "margin_mode": "cross",
            "position_side": position_side,
        }
        if reduce_only:
            body["reduce_only"] = 1
        if client_order_id:
            digits = "".join(c for c in client_order_id if c.isdigit()) or str(int(time.time() * 1000))
            body["client_order_id"] = int(digits[-18:])
        return body

    def swap_market_order(
        self,
        contract_code: str,
        *,
        side: str,
        base_qty: float,
        reduce_only: bool = False,
        client_order_id: str = "",
    ) -> str:
        volume = self.qty_to_contracts(contract_code, base_qty)
        sd = side.lower()
        hedge = self._swap_hedge_mode(contract_code)
        if hedge:
            if reduce_only:
                ps = "short" if sd == "buy" else "long"
            else:
                ps = "long" if sd == "buy" else "short"
            candidates = [ps]
        else:
            candidates = ["both"]

        last_err: Optional[Exception] = None
        for ps in candidates:
            body = self._build_v5_order_body(
                contract_code=contract_code,
                volume=volume,
                side=sd,
                reduce_only=reduce_only,
                position_side=ps,
                client_order_id=client_order_id,
            )
            try:
                raw = self._swap_private("POST", "/v5/trade/order", json_body=body)
                data = _v5_data(raw) or {}
                return str(data.get("order_id_str") or data.get("order_id") or "")
            except HtxError as exc:
                last_err = exc
                msg = str(exc).lower()
                if "1499" in msg or "1500" in msg or "position" in msg:
                    continue
                raise
        if last_err:
            raise last_err
        raise HtxError("swap order failed")

    def ping(self) -> bool:
        try:
            self._spot_public("/v1/common/timestamp")
            return True
        except Exception:
            return False
