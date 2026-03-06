from __future__ import annotations

from packages.backtest.engine import CandleBacktester


def test_strategy_aware_backtest_differs_by_family():
    candles = []
    px = 100.0
    for i in range(60):
        px = px + 2 if i % 10 < 5 else px - 1.5
        candles.append({"open": px - 0.5, "high": px + 1, "low": px - 1, "close": px})

    bt = CandleBacktester()
    trend = bt.run_walk_forward(candles, strategy_family="TrendCore")
    mr = bt.run_walk_forward(candles, strategy_family="RangeMR")
    assert trend[1].trades > 0
    assert mr[1].trades > 0
    assert trend[1].pnl != mr[1].pnl
