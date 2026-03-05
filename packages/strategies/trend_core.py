from __future__ import annotations

from packages.core.models import MarketSnapshot, Regime, StrategySignal
from packages.strategies.base import StrategyPlugin


class TrendCore(StrategyPlugin):
    name = "TrendCore"
    eligible_regimes = {Regime.TREND_UP, Regime.TREND_DOWN}

    def generate(self, snapshot: MarketSnapshot, regime: Regime, config: dict) -> StrategySignal | None:
        if regime not in self.eligible_regimes or snapshot.atr is None:
            return None
        atr_mult = float(config.get("atr_stop_mult", 2.0))
        side = "BUY" if regime == Regime.TREND_UP else "SELL"
        stop = snapshot.price - atr_mult * snapshot.atr if side == "BUY" else snapshot.price + atr_mult * snapshot.atr
        return StrategySignal(
            symbol=snapshot.symbol,
            side=side,
            confidence=float(config.get("base_confidence", 0.55)),
            stop_price=stop,
            take_profit=None,
            reason=f"trend_regime_{regime.value}",
            meta={"time_stop_bars": config.get("time_stop_bars", 12)},
        )
