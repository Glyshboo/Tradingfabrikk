from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict

from packages.core.models import MarketSnapshot


@dataclass
class SymbolProfile:
    vol_signature: float = 0.0
    liquidity_signature: float = 0.0
    slippage_proxy: float = 0.0
    funding_behavior: float = 0.0
    updated_ts: float = 0.0


class SymbolProfileManager:
    def __init__(self, interval_sec: int = 60):
        self.interval_sec = interval_sec
        self._last = 0.0
        self.profiles: Dict[str, SymbolProfile] = {}

    def maybe_update(self, snapshots: Dict[str, MarketSnapshot]) -> None:
        now = time.time()
        if now - self._last < self.interval_sec:
            return
        for sym, snap in snapshots.items():
            spread = (snap.ask - snap.bid) / max(snap.price, 1e-9)
            p = self.profiles.get(sym, SymbolProfile())
            p.vol_signature = snap.atr or p.vol_signature
            p.liquidity_signature = max(0.0, 1.0 - spread * 1000)
            p.slippage_proxy = spread * 0.5
            p.funding_behavior = p.funding_behavior
            p.updated_ts = now
            self.profiles[sym] = p
        self._last = now
