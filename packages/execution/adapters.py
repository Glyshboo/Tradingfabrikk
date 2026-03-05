from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import parse, request
from urllib.error import HTTPError, URLError

from packages.core.models import OrderRequest
from packages.telemetry.logging_utils import log_event


class ExecutionAdapter(Protocol):
    async def place_order(self, order: OrderRequest) -> dict: ...
    async def cancel_all(self, symbol: str | None = None) -> None: ...


class PaperExecutionAdapter:
    def __init__(self) -> None:
        self.orders = []

    async def place_order(self, order: OrderRequest) -> dict:
        payload = {
            "symbol": order.symbol,
            "side": order.side,
            "qty": round(order.qty, 6),
            "type": order.type,
            "reduceOnly": order.reduce_only,
            "status": "FILLED",
            "mode": "paper",
        }
        self.orders.append(payload)
        return payload

    async def cancel_all(self, symbol: str | None = None) -> None:
        _ = symbol


@dataclass
class BinanceRequestError(Exception):
    category: str
    message: str
    status_code: int | None = None
    retryable: bool = False
    endpoint: str | None = None
    request_id: str | None = None
    code: int | None = None
    rate_limit: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.category}: {self.message}"


class LiveExecutionAdapter:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str = "https://fapi.binance.com",
        recv_window: int = 5000,
        timeout_sec: float = 4.0,
        retries: int = 2,
        retry_backoff_sec: float = 0.35,
    ) -> None:
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET", "")
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout_sec = timeout_sec
        self.retries = max(0, retries)
        self.retry_backoff_sec = max(0.05, retry_backoff_sec)

    async def place_order(self, order: OrderRequest) -> dict:
        payload = self._to_binance_order(order)
        response, meta = await self._signed_request("POST", "/fapi/v1/order", payload)
        return {
            "symbol": response.get("symbol", payload["symbol"]),
            "side": response.get("side", payload["side"]),
            "qty": float(payload["quantity"]),
            "type": payload["type"],
            "reduceOnly": payload["reduceOnly"] == "true",
            "status": response.get("status", "SUBMITTED"),
            "mode": "live",
            "request_id": meta["request_id"],
        }

    async def cancel_all(self, symbol: str | None = None) -> None:
        params = {}
        if symbol:
            params["symbol"] = symbol.upper().replace("/", "")
        await self._signed_request("DELETE", "/fapi/v1/allOpenOrders", params)

    def _to_binance_order(self, order: OrderRequest) -> dict[str, str]:
        symbol = order.symbol.upper().replace("/", "")
        side = order.side.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise BinanceRequestError("validation", f"Unsupported side '{order.side}'")
        if order.qty <= 0:
            raise BinanceRequestError("validation", "qty must be > 0")

        return {
            "symbol": symbol,
            "side": side,
            "type": order.type.upper().strip() or "MARKET",
            "quantity": f"{order.qty:.8f}".rstrip("0").rstrip("."),
            "reduceOnly": "true" if order.reduce_only else "false",
        }

    async def _signed_request(self, method: str, endpoint: str, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.api_key or not self.api_secret:
            raise BinanceRequestError("auth", "Missing Binance API credentials", endpoint=endpoint)

        signed_params = dict(params)
        signed_params["timestamp"] = int(time.time() * 1000)
        signed_params["recvWindow"] = self.recv_window
        query = parse.urlencode(signed_params)
        signature = hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        signed_params["signature"] = signature
        encoded = parse.urlencode(signed_params).encode("utf-8")
        url = f"{self.base_url}{endpoint}"

        request_id = str(uuid.uuid4())
        headers = {
            "X-MBX-APIKEY": self.api_key,
            "X-REQUEST-ID": request_id,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        attempt = 0
        while True:
            start = time.perf_counter()
            try:
                response, response_headers = await asyncio.to_thread(self._request_once, method, url, encoded, headers)
                latency_ms = (time.perf_counter() - start) * 1000
                meta = self._request_meta(request_id, endpoint, latency_ms, response_headers)
                log_event("execution_http", {"endpoint": endpoint, "latency_ms": latency_ms, "request_id": request_id, **meta})
                return response, {"request_id": request_id, **meta}
            except BinanceRequestError as exc:
                latency_ms = (time.perf_counter() - start) * 1000
                telemetry = {
                    "request_id": request_id,
                    "endpoint": endpoint,
                    "latency_ms": latency_ms,
                    "error_category": exc.category,
                    "status_code": exc.status_code,
                }
                if exc.rate_limit:
                    telemetry.update(exc.rate_limit)
                log_event("execution_http_error", telemetry)
                if exc.retryable and attempt < self.retries:
                    await asyncio.sleep(self.retry_backoff_sec * (2**attempt))
                    attempt += 1
                    continue
                raise

    def _request_once(
        self,
        method: str,
        url: str,
        encoded: bytes,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        req = request.Request(url=url, method=method, data=encoded, headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
                parsed_body = json.loads(body) if body else {}
                return parsed_body, dict(resp.headers)
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            payload = json.loads(text) if text.startswith("{") else {}
            code = payload.get("code") if isinstance(payload, dict) else None
            msg = payload.get("msg") if isinstance(payload, dict) else text or str(exc)
            category = "client"
            retryable = False
            if exc.code in (401, 403):
                category = "auth"
            elif exc.code in (418, 429):
                category = "rate_limit"
                retryable = True
            elif exc.code >= 500:
                category = "server"
                retryable = True
            raise BinanceRequestError(
                category=category,
                message=msg,
                status_code=exc.code,
                retryable=retryable,
                code=code,
                rate_limit={
                    "retry_after": exc.headers.get("Retry-After"),
                    "x_mbx_used_weight_1m": exc.headers.get("x-mbx-used-weight-1m"),
                    "x_mbx_order_count_10s": exc.headers.get("x-mbx-order-count-10s"),
                    "x_mbx_order_count_1m": exc.headers.get("x-mbx-order-count-1m"),
                },
            )
        except (TimeoutError, socket.timeout) as exc:
            raise BinanceRequestError("timeout", str(exc), retryable=True) from exc
        except URLError as exc:
            raise BinanceRequestError("network", str(exc), retryable=True) from exc

    def _request_meta(self, request_id: str, endpoint: str, latency_ms: float, headers: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "endpoint": endpoint,
            "latency_ms": round(latency_ms, 2),
            "x_mbx_used_weight_1m": headers.get("x-mbx-used-weight-1m"),
            "x_mbx_order_count_10s": headers.get("x-mbx-order-count-10s"),
            "x_mbx_order_count_1m": headers.get("x-mbx-order-count-1m"),
        }


def format_order(symbol: str, side: str, qty: float, reduce_only: bool = False) -> OrderRequest:
    return OrderRequest(symbol=symbol, side=side, qty=max(qty, 0.0), reduce_only=reduce_only)
