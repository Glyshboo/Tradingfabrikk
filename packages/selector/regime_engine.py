from __future__ import annotations

from packages.core.models import MarketSnapshot, Regime


class RegimeEngine:
    def classify(self, snap: MarketSnapshot) -> Regime:
        spread_bps = ((snap.ask - snap.bid) / max(snap.price, 1e-9)) * 10000
        if spread_bps > 8:
            return Regime.ILLIQUID
        atr_ratio = (snap.atr or 0.0) / max(snap.price, 1e-9)
        if snap.atr and atr_ratio > 0.025:
            return Regime.HIGH_VOL
        if snap.rsi is not None:
            if snap.rsi > 58 and (snap.candle_close or snap.price) >= snap.price * 0.998:
                return Regime.TREND_UP
            if snap.rsi < 42 and (snap.candle_close or snap.price) <= snap.price * 1.002:
                return Regime.TREND_DOWN
        return Regime.RANGE
