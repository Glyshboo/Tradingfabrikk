from __future__ import annotations

from packages.core.models import MarketSnapshot, Regime, StrategyContext, StrategySignal
from packages.strategies.base import StrategyPlugin


class RangeMR(StrategyPlugin):
    name = "RangeMR"
    eligible_regimes = {Regime.RANGE}

    def generate_for_context(self, context: StrategyContext) -> StrategySignal | None:
        snapshot = context.snapshot
        regime = context.regime
        config = context.config
        if regime != Regime.RANGE or snapshot.rsi is None or snapshot.atr is None:
            return None
        low = float(config.get("rsi_low", 35))
        high = float(config.get("rsi_high", 65))
        if snapshot.rsi <= low:
            side = "BUY"
        elif snapshot.rsi >= high:
            side = "SELL"
        else:
            return None
        stop = snapshot.price - snapshot.atr if side == "BUY" else snapshot.price + snapshot.atr
        return StrategySignal(
            symbol=snapshot.symbol,
            side=side,
            confidence=float(config.get("base_confidence", 0.52)),
            stop_price=stop,
            take_profit=snapshot.price,
            reason="range_mean_reversion",
            meta={"rsi": snapshot.rsi},
        )

    def generate(self, snapshot: MarketSnapshot, regime: Regime, config: dict) -> StrategySignal | None:
        return self.generate_for_context(StrategyContext(snapshot=snapshot, regime=regime, config=config))
