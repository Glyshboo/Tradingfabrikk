from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.models import MarketSnapshot, Regime, StrategySignal


class StrategyPlugin(ABC):
    name: str
    eligible_regimes: set[Regime]

    @abstractmethod
    def generate(self, snapshot: MarketSnapshot, regime: Regime, config: dict) -> StrategySignal | None:
        raise NotImplementedError
