from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from packages.core.models import Regime, StrategyComposition, StrategyContext, StrategySignal
from packages.strategies.base import EntryFamily, ExitPack, FilterModule, StrategyEvaluator, StrategyPlugin
from packages.strategies.entry_families import (
    BreakoutRetestEntryFamily,
    FailedBreakoutFadeEntryFamily,
    TrendPullbackEntryFamily,
)


class LegacyEntryFamily(EntryFamily):
    def __init__(self, name: str, strategy: StrategyPlugin):
        self.name = name
        self._strategy = strategy

    def generate_entry(self, context: StrategyContext) -> StrategySignal | None:
        return self._strategy.generate_for_context(context)


class SignalSanityFilter(FilterModule):
    name = "signal_sanity"

    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        if signal.side not in {"BUY", "SELL"}:
            return False
        if signal.confidence <= 0.0:
            return False
        return True


class RegimeGuardFilter(FilterModule):
    name = "regime_guard"

    def __init__(self, eligible_regimes: dict[str, Iterable[Regime]]):
        self._eligible = {k: set(v) for k, v in eligible_regimes.items()}

    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        family = context.config.get("composition", {}).get("entry_family") or context.config.get("entry_family")
        if not isinstance(family, str):
            return True
        allowed = self._eligible.get(family)
        if not allowed:
            return False
        return context.regime in allowed


class PassthroughExitPack(ExitPack):
    name = "passthrough"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        return signal


class ProtectiveExitPack(ExitPack):
    name = "protective"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        if signal.stop_price is None:
            return None
        meta = dict(signal.meta)
        meta.setdefault("exit_pack", self.name)
        return replace(signal, meta=meta)


def build_strategy_evaluator(strategies: dict[str, StrategyPlugin]) -> StrategyEvaluator:
    eligible_regimes = {name: set(getattr(plugin, "eligible_regimes", set())) for name, plugin in strategies.items()}
    entry_families: dict[str, EntryFamily] = {name: LegacyEntryFamily(name, strategy) for name, strategy in strategies.items()}
    entry_families.update(
        {
            "BreakoutRetest": BreakoutRetestEntryFamily(),
            "TrendPullback": TrendPullbackEntryFamily(),
            "FailedBreakoutFade": FailedBreakoutFadeEntryFamily(),
        }
    )
    eligible_regimes.update(
        {
            "BreakoutRetest": {Regime.TREND_UP, Regime.TREND_DOWN, Regime.HIGH_VOL},
            "TrendPullback": {Regime.TREND_UP, Regime.TREND_DOWN},
            "FailedBreakoutFade": {Regime.RANGE, Regime.HIGH_VOL, Regime.TREND_UP, Regime.TREND_DOWN},
        }
    )
    return StrategyEvaluator(
        strategies=strategies,
        entry_families=entry_families,
        filter_modules={
            "signal_sanity": SignalSanityFilter(),
            "regime_guard": RegimeGuardFilter(eligible_regimes=eligible_regimes),
        },
        filter_packs={
            "none": [],
            "safe": ["signal_sanity", "regime_guard"],
        },
        exit_packs={"passthrough": PassthroughExitPack(), "protective": ProtectiveExitPack()},
        default_compositions={
            "TrendCore": StrategyComposition(entry_family="TrendCore", filter_pack="safe", exit_pack="passthrough"),
            "RangeMR": StrategyComposition(entry_family="RangeMR", filter_pack="safe", exit_pack="passthrough"),
            "BreakoutRetest": StrategyComposition(entry_family="BreakoutRetest", filter_pack="safe", exit_pack="passthrough"),
            "TrendPullback": StrategyComposition(entry_family="TrendPullback", filter_pack="safe", exit_pack="passthrough"),
            "FailedBreakoutFade": StrategyComposition(entry_family="FailedBreakoutFade", filter_pack="safe", exit_pack="passthrough"),
        },
    )
