from __future__ import annotations

from typing import Protocol

from packages.core.models import OrderRequest


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


class LiveExecutionAdapter:
    def __init__(self) -> None:
        # Placeholder for signed REST calls (place/cancel only, rate-limited).
        pass

    async def place_order(self, order: OrderRequest) -> dict:
        return {
            "symbol": order.symbol,
            "side": order.side,
            "qty": round(order.qty, 6),
            "type": order.type,
            "reduceOnly": order.reduce_only,
            "status": "SUBMITTED",
            "mode": "live_stub",
        }

    async def cancel_all(self, symbol: str | None = None) -> None:
        _ = symbol


def format_order(symbol: str, side: str, qty: float, reduce_only: bool = False) -> OrderRequest:
    return OrderRequest(symbol=symbol, side=side, qty=max(qty, 0.0), reduce_only=reduce_only)
