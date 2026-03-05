from __future__ import annotations

from packages.core.models import MarketSnapshot, Regime


class RegimeEngine:
    def classify(self, snap: MarketSnapshot) -> Regime:
        spread_bps = ((snap.ask - snap.bid) / max(snap.price, 1e-9)) * 10000
        if spread_bps > 8:
            return Regime.ILLIQUID
        if snap.atr and snap.atr > 1.8:
            return Regime.HIGH_VOL
        if snap.rsi is not None:
            if snap.rsi > 58:
                return Regime.TREND_UP
            if snap.rsi < 42:
                return Regime.TREND_DOWN
        return Regime.RANGE
