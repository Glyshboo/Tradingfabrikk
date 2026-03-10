from __future__ import annotations

from packages.backtest.engine import CandleBacktester
from packages.core.models import MarketSnapshot, Regime, StrategyContext
from packages.strategies.range_mr import RangeMR
from packages.strategies.trend_core import TrendCore


def _side_to_pos(side: str | None) -> int:
    if side == "BUY":
        return 1
    if side == "SELL":
        return -1
    return 0


def test_trend_core_signal_parity_trend_up_and_down() -> None:
    strategy = TrendCore()
    backtester = CandleBacktester()
    cfg = {"atr_stop_mult": 2.0, "base_confidence": 0.55}

    up_snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        price=101.0,
        bid=101.0,
        ask=101.0,
        candle_close=100.0,
        atr=1.5,
        rsi=61.0,
        ts=1.0,
    )
    down_snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        price=99.0,
        bid=99.0,
        ask=99.0,
        candle_close=100.0,
        atr=1.7,
        rsi=39.0,
        ts=2.0,
    )

    runtime_up = strategy.generate_for_context(StrategyContext(snapshot=up_snapshot, regime=Regime.TREND_UP, config=cfg))
    runtime_down = strategy.generate_for_context(StrategyContext(snapshot=down_snapshot, regime=Regime.TREND_DOWN, config=cfg))

    backtest_up = backtester.signal_for_snapshot("TrendCore", up_snapshot, Regime.TREND_UP, cfg)
    backtest_down = backtester.signal_for_snapshot("TrendCore", down_snapshot, Regime.TREND_DOWN, cfg)

    assert _side_to_pos(runtime_up.side if runtime_up else None) == backtest_up == 1
    assert _side_to_pos(runtime_down.side if runtime_down else None) == backtest_down == -1


def test_range_mr_signal_parity_in_range() -> None:
    strategy = RangeMR()
    backtester = CandleBacktester()
    cfg = {"rsi_low": 35, "rsi_high": 65, "base_confidence": 0.52}
    snapshot = MarketSnapshot(
        symbol="ETHUSDT",
        price=100.0,
        bid=100.0,
        ask=100.0,
        candle_close=100.0,
        atr=1.2,
        rsi=72.0,
        ts=1.0,
    )

    runtime_signal = strategy.generate_for_context(StrategyContext(snapshot=snapshot, regime=Regime.RANGE, config=cfg))
    backtest_signal = backtester.signal_for_snapshot("RangeMR", snapshot, Regime.RANGE, cfg)

    assert _side_to_pos(runtime_signal.side if runtime_signal else None) == backtest_signal == -1
