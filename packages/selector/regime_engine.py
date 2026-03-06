from __future__ import annotations

from packages.core.models import MarketSnapshot, Regime


class RegimeEngine:
    def classify(self, snap: MarketSnapshot) -> Regime:
        spread_bps = ((snap.ask - snap.bid) / max(snap.price, 1e-9)) * 10000
        if spread_bps > 10:
            return Regime.ILLIQUID
        atr_ratio = (snap.atr or 0.0) / max(snap.price, 1e-9)
        if snap.atr and atr_ratio > 0.03:
            return Regime.HIGH_VOL
        if snap.rsi is not None:
            reference_close = snap.candle_close if snap.candle_close is not None else snap.price
            momentum = (snap.price - reference_close) / max(reference_close, 1e-9)
            if snap.rsi >= 55 and momentum >= -0.001:
                return Regime.TREND_UP
            if snap.rsi <= 45 and momentum <= 0.001:
                return Regime.TREND_DOWN
        return Regime.RANGE
