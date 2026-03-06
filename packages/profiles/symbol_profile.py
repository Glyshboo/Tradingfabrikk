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

    def maybe_update(self, snapshots: Dict[str, MarketSnapshot], funding_rates: Dict[str, float] | None = None) -> None:
        now = time.time()
        if now - self._last < self.interval_sec:
            return
        for sym, snap in snapshots.items():
            spread = (snap.ask - snap.bid) / max(snap.price, 1e-9)
            atr_ratio = (snap.atr or 0.0) / max(snap.price, 1e-9)
            p = self.profiles.get(sym, SymbolProfile())
            # smoother volatility signature to avoid profile jitter
            p.vol_signature = round(0.6 * p.vol_signature + 0.4 * atr_ratio, 8)
            p.liquidity_signature = max(0.0, min(1.0, 1.0 - spread * 1500))
            p.slippage_proxy = max(0.0, spread * (0.35 + atr_ratio * 5.0))
            p.funding_behavior = float((funding_rates or {}).get(sym, p.funding_behavior))
            p.updated_ts = now
            self.profiles[sym] = p
        self._last = now


def effective_backtest_costs(
    profile: SymbolProfile | None,
    base_fee_bps: float = 4.0,
    base_slippage_bps: float = 2.0,
) -> tuple[float, float]:
    if profile is None:
        return base_fee_bps, base_slippage_bps

    liquidity_penalty = max(0.0, 1.0 - profile.liquidity_signature) * 4.0
    fee_bps = base_fee_bps + liquidity_penalty
    slippage_bps = base_slippage_bps + max(0.0, profile.slippage_proxy) * 10000
    return fee_bps, slippage_bps
