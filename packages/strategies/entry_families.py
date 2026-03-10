from __future__ import annotations

from packages.core.models import Regime, StrategyContext, StrategySignal
from packages.strategies.base import EntryFamily, StrategyPlugin


class BreakoutRetestEntryFamily(EntryFamily):
    name = "BreakoutRetest"

    def generate_entry(self, context: StrategyContext) -> StrategySignal | None:
        snap = context.snapshot
        cfg = context.config
        if snap.atr is None or snap.rsi is None or snap.trend_slope is None or snap.breakout_distance_from_recent_range is None:
            return None

        min_compression = float(cfg.get("min_range_compression", 0.2))
        if (snap.range_compression_score or 0.0) < min_compression:
            return None

        min_trend_slope = float(cfg.get("min_trend_slope", 0.0004))
        min_reclaim_distance = float(cfg.get("min_reclaim_distance_atr", 0.02))
        max_retest_distance = float(cfg.get("max_retest_distance_atr", 0.35))
        atr_stop_mult = float(cfg.get("atr_stop_mult", 1.8))
        base_confidence = float(cfg.get("base_confidence", 0.57))

        distance = float(snap.breakout_distance_from_recent_range)
        side: str | None = None
        if (
            snap.trend_slope >= min_trend_slope
            and min_reclaim_distance <= distance <= max_retest_distance
            and snap.rsi >= float(cfg.get("long_rsi_min", 52.0))
        ):
            side = "BUY"
        elif (
            snap.trend_slope <= -min_trend_slope
            and -max_retest_distance <= distance <= -min_reclaim_distance
            and snap.rsi <= float(cfg.get("short_rsi_max", 48.0))
        ):
            side = "SELL"

        if side is None:
            return None

        stop = snap.price - (atr_stop_mult * snap.atr) if side == "BUY" else snap.price + (atr_stop_mult * snap.atr)
        return StrategySignal(
            symbol=snap.symbol,
            side=side,
            confidence=base_confidence,
            stop_price=stop,
            take_profit=None,
            reason="breakout_retest_reclaim",
            meta={"entry_family": self.name, "distance_atr": distance},
        )


class TrendPullbackEntryFamily(EntryFamily):
    name = "TrendPullback"

    def generate_entry(self, context: StrategyContext) -> StrategySignal | None:
        snap = context.snapshot
        cfg = context.config
        if (
            snap.atr is None
            or snap.rsi is None
            or snap.trend_slope is None
            or snap.breakout_distance_from_recent_range is None
            or snap.candle_close is None
        ):
            return None

        min_trend_slope = float(cfg.get("min_trend_slope", 0.0005))
        max_pullback_distance = float(cfg.get("max_pullback_distance_atr", 0.45))
        max_chase_distance = float(cfg.get("max_chase_distance_atr", 0.75))
        atr_stop_mult = float(cfg.get("atr_stop_mult", 2.0))
        base_confidence = float(cfg.get("base_confidence", 0.56))
        distance = float(snap.breakout_distance_from_recent_range)

        side: str | None = None
        if (
            snap.trend_slope >= min_trend_slope
            and -max_pullback_distance <= distance <= max_chase_distance
            and float(cfg.get("long_rsi_pullback_min", 45.0)) <= snap.rsi <= float(cfg.get("long_rsi_confirm_max", 63.0))
            and snap.price >= snap.candle_close
        ):
            side = "BUY"
        elif (
            snap.trend_slope <= -min_trend_slope
            and -max_chase_distance <= distance <= max_pullback_distance
            and float(cfg.get("short_rsi_confirm_min", 37.0)) <= snap.rsi <= float(cfg.get("short_rsi_pullback_max", 55.0))
            and snap.price <= snap.candle_close
        ):
            side = "SELL"

        if side is None:
            return None

        stop = snap.price - (atr_stop_mult * snap.atr) if side == "BUY" else snap.price + (atr_stop_mult * snap.atr)
        return StrategySignal(
            symbol=snap.symbol,
            side=side,
            confidence=base_confidence,
            stop_price=stop,
            take_profit=None,
            reason="trend_pullback_continuation",
            meta={"entry_family": self.name, "distance_atr": distance},
        )


class FailedBreakoutFadeEntryFamily(EntryFamily):
    name = "FailedBreakoutFade"

    def generate_entry(self, context: StrategyContext) -> StrategySignal | None:
        snap = context.snapshot
        cfg = context.config
        if snap.atr is None or snap.rsi is None or snap.trend_slope is None or snap.breakout_distance_from_recent_range is None:
            return None

        min_breakout = float(cfg.get("min_failed_breakout_distance_atr", 0.18))
        min_reversal_slope = float(cfg.get("min_reversal_slope", 0.00035))
        min_compression = float(cfg.get("min_range_compression", 0.15))
        if (snap.range_compression_score or 0.0) < min_compression:
            return None

        distance = float(snap.breakout_distance_from_recent_range)
        atr_stop_mult = float(cfg.get("atr_stop_mult", 1.4))
        base_confidence = float(cfg.get("base_confidence", 0.59))

        side: str | None = None
        if (
            distance >= min_breakout
            and snap.trend_slope <= -min_reversal_slope
            and snap.rsi >= float(cfg.get("fade_short_rsi_min", 56.0))
        ):
            side = "SELL"
        elif (
            distance <= -min_breakout
            and snap.trend_slope >= min_reversal_slope
            and snap.rsi <= float(cfg.get("fade_long_rsi_max", 44.0))
        ):
            side = "BUY"

        if side is None:
            return None

        stop = snap.price - (atr_stop_mult * snap.atr) if side == "BUY" else snap.price + (atr_stop_mult * snap.atr)
        return StrategySignal(
            symbol=snap.symbol,
            side=side,
            confidence=base_confidence,
            stop_price=stop,
            take_profit=None,
            reason="failed_breakout_fade",
            meta={"entry_family": self.name, "distance_atr": distance},
        )


class EntryFamilyStrategyPlugin(StrategyPlugin):
    def __init__(self, family: EntryFamily, eligible_regimes: set[Regime]):
        self.name = family.name
        self.eligible_regimes = set(eligible_regimes)
        self._family = family

    def generate_for_context(self, context: StrategyContext) -> StrategySignal | None:
        if context.regime not in self.eligible_regimes:
            return None
        return self._family.generate_entry(context)

    def generate(self, snapshot, regime, config):
        return self.generate_for_context(StrategyContext(snapshot=snapshot, regime=regime, config=config))
