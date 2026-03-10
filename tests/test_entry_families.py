from __future__ import annotations

from packages.backtest.engine import CandleBacktester
from packages.core.models import MarketSnapshot, Regime, StrategyContext
from packages.strategies.entry_families import (
    BreakoutRetestEntryFamily,
    FailedBreakoutFadeEntryFamily,
    TrendPullbackEntryFamily,
)


def _side(signal) -> int:
    if not signal:
        return 0
    return 1 if signal.side == "BUY" else -1 if signal.side == "SELL" else 0


def test_breakout_retest_positive_and_negative_cases() -> None:
    family = BreakoutRetestEntryFamily()
    cfg = {
        "min_range_compression": 0.2,
        "min_trend_slope": 0.0004,
        "min_reclaim_distance_atr": 0.02,
        "max_retest_distance_atr": 0.35,
    }
    positive = MarketSnapshot(
        symbol="BTCUSDT",
        price=101.0,
        bid=101.0,
        ask=101.0,
        candle_close=100.6,
        atr=1.0,
        rsi=56.0,
        trend_slope=0.001,
        breakout_distance_from_recent_range=0.2,
        range_compression_score=0.35,
        ts=1.0,
    )
    negative = MarketSnapshot(
        symbol="BTCUSDT",
        price=101.0,
        bid=101.0,
        ask=101.0,
        candle_close=100.6,
        atr=1.0,
        rsi=48.0,
        trend_slope=0.001,
        breakout_distance_from_recent_range=0.2,
        range_compression_score=0.1,
        ts=1.0,
    )

    assert _side(family.generate_entry(StrategyContext(snapshot=positive, regime=Regime.TREND_UP, config=cfg))) == 1
    assert family.generate_entry(StrategyContext(snapshot=negative, regime=Regime.TREND_UP, config=cfg)) is None


def test_trend_pullback_positive_and_negative_cases() -> None:
    family = TrendPullbackEntryFamily()
    cfg = {"min_trend_slope": 0.0005, "max_pullback_distance_atr": 0.45, "max_chase_distance_atr": 0.75}
    positive = MarketSnapshot(
        symbol="ETHUSDT",
        price=100.8,
        bid=100.8,
        ask=100.8,
        candle_close=100.5,
        atr=1.2,
        rsi=52.0,
        trend_slope=0.0008,
        breakout_distance_from_recent_range=0.1,
        range_compression_score=0.25,
        ts=2.0,
    )
    negative = MarketSnapshot(
        symbol="ETHUSDT",
        price=100.2,
        bid=100.2,
        ask=100.2,
        candle_close=100.5,
        atr=1.2,
        rsi=70.0,
        trend_slope=0.0008,
        breakout_distance_from_recent_range=1.2,
        range_compression_score=0.25,
        ts=2.0,
    )

    assert _side(family.generate_entry(StrategyContext(snapshot=positive, regime=Regime.TREND_UP, config=cfg))) == 1
    assert family.generate_entry(StrategyContext(snapshot=negative, regime=Regime.TREND_UP, config=cfg)) is None


def test_failed_breakout_fade_positive_and_negative_cases() -> None:
    family = FailedBreakoutFadeEntryFamily()
    cfg = {"min_failed_breakout_distance_atr": 0.18, "min_reversal_slope": 0.00035, "min_range_compression": 0.15}
    positive = MarketSnapshot(
        symbol="SOLUSDT",
        price=99.4,
        bid=99.4,
        ask=99.4,
        candle_close=99.9,
        atr=0.9,
        rsi=62.0,
        trend_slope=-0.0007,
        breakout_distance_from_recent_range=0.28,
        range_compression_score=0.3,
        ts=3.0,
    )
    negative = MarketSnapshot(
        symbol="SOLUSDT",
        price=99.4,
        bid=99.4,
        ask=99.4,
        candle_close=99.9,
        atr=0.9,
        rsi=52.0,
        trend_slope=-0.0002,
        breakout_distance_from_recent_range=0.28,
        range_compression_score=0.3,
        ts=3.0,
    )

    assert _side(family.generate_entry(StrategyContext(snapshot=positive, regime=Regime.RANGE, config=cfg))) == -1
    assert family.generate_entry(StrategyContext(snapshot=negative, regime=Regime.RANGE, config=cfg)) is None


def test_runtime_backtest_parity_for_new_entry_families() -> None:
    backtester = CandleBacktester()

    breakout_snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        price=101.0,
        bid=101.0,
        ask=101.0,
        candle_close=100.2,
        atr=1.0,
        rsi=57.0,
        trend_slope=0.001,
        breakout_distance_from_recent_range=0.15,
        range_compression_score=0.4,
        ts=1.0,
    )
    pullback_snapshot = MarketSnapshot(
        symbol="ETHUSDT",
        price=99.2,
        bid=99.2,
        ask=99.2,
        candle_close=99.4,
        atr=1.0,
        rsi=48.0,
        trend_slope=-0.001,
        breakout_distance_from_recent_range=0.2,
        range_compression_score=0.3,
        ts=2.0,
    )
    fade_snapshot = MarketSnapshot(
        symbol="SOLUSDT",
        price=88.0,
        bid=88.0,
        ask=88.0,
        candle_close=88.2,
        atr=1.0,
        rsi=39.0,
        trend_slope=0.0009,
        breakout_distance_from_recent_range=-0.25,
        range_compression_score=0.4,
        ts=3.0,
    )

    assert backtester.signal_for_snapshot("BreakoutRetest", breakout_snapshot, Regime.TREND_UP, {}) == 1
    assert backtester.signal_for_snapshot("TrendPullback", pullback_snapshot, Regime.TREND_DOWN, {}) == -1
    assert backtester.signal_for_snapshot("FailedBreakoutFade", fade_snapshot, Regime.RANGE, {}) == 1
