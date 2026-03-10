from __future__ import annotations

from typing import Iterable

from packages.core.models import Regime, StrategyComposition, StrategyContext, StrategySignal
from packages.strategies.base import EntryFamily, FilterModule, StrategyEvaluator, StrategyPlugin
from packages.strategies.exits import (
    ATRTrailExitPack,
    FixedRRExitPack,
    PartialTPRunnerExitPack,
    PassthroughExitPack,
    ProtectiveExitPack,
    TimeDecayExitPack,
)
from packages.strategies.entry_families import (
    BreakoutRetestEntryFamily,
    FailedBreakoutFadeEntryFamily,
    TrendPullbackEntryFamily,
)
from packages.strategies.filters import CompressionGate, HTFAlignmentGate, RangeQualityGate, SessionGate, TrendSlopeGate


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
            "trend_slope_gate": TrendSlopeGate(),
            "session_gate": SessionGate(),
            "compression_gate": CompressionGate(),
            "range_quality_gate": RangeQualityGate(),
            "htf_alignment_gate": HTFAlignmentGate(),
        },
        filter_packs={
            "none": [],
            "safe": ["signal_sanity", "regime_guard"],
            "trend_baseline": ["signal_sanity", "regime_guard", "trend_slope_gate", "htf_alignment_gate"],
            "range_baseline": ["signal_sanity", "regime_guard", "range_quality_gate", "session_gate"],
            "breakout_baseline": ["signal_sanity", "regime_guard", "compression_gate", "session_gate"],
        },
        exit_packs={
            "passthrough": PassthroughExitPack(),
            "protective": ProtectiveExitPack(),
            "fixed_rr": FixedRRExitPack(),
            "atr_trail": ATRTrailExitPack(),
            "partial_tp_runner": PartialTPRunnerExitPack(),
            "time_decay_exit": TimeDecayExitPack(),
        },
        default_compositions={
            "TrendCore": StrategyComposition(entry_family="TrendCore", filter_pack="safe", exit_pack="passthrough"),
            "RangeMR": StrategyComposition(entry_family="RangeMR", filter_pack="safe", exit_pack="passthrough"),
            "BreakoutRetest": StrategyComposition(entry_family="BreakoutRetest", filter_pack="safe", exit_pack="passthrough"),
            "TrendPullback": StrategyComposition(entry_family="TrendPullback", filter_pack="safe", exit_pack="passthrough"),
            "FailedBreakoutFade": StrategyComposition(entry_family="FailedBreakoutFade", filter_pack="safe", exit_pack="passthrough"),
        },
    )
