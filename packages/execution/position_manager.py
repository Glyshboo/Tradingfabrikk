from __future__ import annotations

import time
from typing import Dict

from packages.core.models import MarketSnapshot, PositionState


class PositionManager:
    def __init__(self) -> None:
        self.state: Dict[str, dict] = {}

    def on_entry(self, symbol: str, side: str, qty: float, price: float, signal_meta: dict | None = None) -> None:
        if qty <= 0:
            return
        self.state[symbol] = {
            "side": side,
            "qty": qty,
            "entry_price": price,
            "stop_price": (signal_meta or {}).get("stop_price"),
            "take_profit": (signal_meta or {}).get("take_profit"),
            "trail_mult": (signal_meta or {}).get("trail_mult", 1.5),
            "time_stop_bars": int((signal_meta or {}).get("time_stop_bars", 0)),
            "bars_open": 0,
            "peak_price": price,
            "ts": time.time(),
        }

    def on_bar(self, symbol: str) -> None:
        if symbol in self.state:
            self.state[symbol]["bars_open"] += 1

    def should_exit(self, symbol: str, snap: MarketSnapshot) -> str | None:
        pos = self.state.get(symbol)
        if not pos:
            return None
        side = pos["side"]
        price = snap.price
        atr = snap.atr or 0.0

        if side == "BUY":
            pos["peak_price"] = max(pos["peak_price"], price)
            trail = pos["peak_price"] - (atr * pos["trail_mult"] if atr else 0)
            if pos.get("stop_price") and price <= pos["stop_price"]:
                return "stop_loss"
            if atr and price <= trail and trail > 0:
                return "trailing_stop"
            if pos.get("take_profit") and price >= pos["take_profit"]:
                return "take_profit"
        else:
            pos["peak_price"] = min(pos["peak_price"], price)
            trail = pos["peak_price"] + (atr * pos["trail_mult"] if atr else 0)
            if pos.get("stop_price") and price >= pos["stop_price"]:
                return "stop_loss"
            if atr and price >= trail and trail > 0:
                return "trailing_stop"
            if pos.get("take_profit") and price <= pos["take_profit"]:
                return "take_profit"

        if pos.get("time_stop_bars", 0) > 0 and pos.get("bars_open", 0) >= pos["time_stop_bars"]:
            return "time_stop"
        return None

    def clear(self, symbol: str) -> None:
        self.state.pop(symbol, None)
