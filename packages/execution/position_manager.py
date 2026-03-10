from __future__ import annotations

import time
from typing import Dict

from packages.core.models import MarketSnapshot


class PositionManager:
    def __init__(self) -> None:
        self.state: Dict[str, dict] = {}

    def on_entry(self, symbol: str, side: str, qty: float, price: float, signal_meta: dict | None = None) -> None:
        if qty <= 0:
            return
        meta = signal_meta or {}
        self.state[symbol] = {
            "side": side,
            "qty": qty,
            "entry_price": price,
            "stop_price": meta.get("stop_price"),
            "take_profit": meta.get("take_profit"),
            "exit_pack": meta.get("exit_pack", "passthrough"),
            "trail_mult": meta.get("trail_mult", 1.5),
            "time_stop_bars": int(meta.get("time_stop_bars", 0)),
            "bars_open": 0,
            "peak_price": price,
            "partial_take_profit": meta.get("partial_take_profit"),
            "partial_fraction": float(meta.get("partial_fraction", 0.0)),
            "partial_taken": False,
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
            if pos.get("stop_price") and price <= pos["stop_price"]:
                return "stop_loss"
            if pos.get("take_profit") and price >= pos["take_profit"]:
                return "take_profit"
            if pos.get("partial_take_profit") and not pos.get("partial_taken") and price >= pos["partial_take_profit"]:
                pos["partial_taken"] = True
                return "partial_take_profit"
            if pos.get("trail_mult", 0) > 0 and atr > 0 and pos.get("exit_pack") in {"atr_trail", "partial_tp_runner"}:
                trail = pos["peak_price"] - (atr * float(pos["trail_mult"]))
                if trail > 0 and price <= trail:
                    return "trailing_stop"
        else:
            pos["peak_price"] = min(pos["peak_price"], price)
            if pos.get("stop_price") and price >= pos["stop_price"]:
                return "stop_loss"
            if pos.get("take_profit") and price <= pos["take_profit"]:
                return "take_profit"
            if pos.get("partial_take_profit") and not pos.get("partial_taken") and price <= pos["partial_take_profit"]:
                pos["partial_taken"] = True
                return "partial_take_profit"
            if pos.get("trail_mult", 0) > 0 and atr > 0 and pos.get("exit_pack") in {"atr_trail", "partial_tp_runner"}:
                trail = pos["peak_price"] + (atr * float(pos["trail_mult"]))
                if trail > 0 and price >= trail:
                    return "trailing_stop"

        if pos.get("time_stop_bars", 0) > 0 and pos.get("bars_open", 0) >= pos["time_stop_bars"]:
            return "time_stop"
        return None

    def reduce_position(self, symbol: str, fraction: float) -> float:
        pos = self.state.get(symbol)
        if not pos:
            return 0.0
        f = max(0.0, min(1.0, float(fraction)))
        if f <= 0:
            return 0.0
        qty_before = float(pos.get("qty", 0.0))
        reduce_qty = qty_before * f
        remaining = max(0.0, qty_before - reduce_qty)
        pos["qty"] = remaining
        if remaining <= 1e-12:
            self.clear(symbol)
        return reduce_qty

    def clear(self, symbol: str) -> None:
        self.state.pop(symbol, None)
