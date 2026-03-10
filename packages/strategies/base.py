from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.models import MarketSnapshot, Regime, StrategyContext, StrategySignal


class StrategyPlugin(ABC):
    name: str
    eligible_regimes: set[Regime]

    @abstractmethod
    def generate_for_context(self, context: StrategyContext) -> StrategySignal | None:
        raise NotImplementedError

    @abstractmethod
    def generate(self, snapshot: MarketSnapshot, regime: Regime, config: dict) -> StrategySignal | None:
        return self.generate_for_context(StrategyContext(snapshot=snapshot, regime=regime, config=config))
