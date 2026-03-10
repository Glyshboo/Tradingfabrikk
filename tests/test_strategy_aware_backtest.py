from __future__ import annotations

from packages.backtest.engine import CandleBacktester


def test_strategy_aware_backtest_differs_by_family():
    candles = []
    px = 100.0
    for i in range(80):
        if i % 12 < 5:
            px += 1.0
        elif i % 12 < 9:
            px -= 0.6
        else:
            px += -0.2 if i % 2 else 0.2
        candles.append({"open": px - 0.5, "high": px + 1, "low": px - 1, "close": px})

    bt = CandleBacktester()
    trend = bt.run_walk_forward(candles, strategy_family="TrendCore")
    mr = bt.run_walk_forward(candles, strategy_family="RangeMR", strategy_config={"rsi_low": 45, "rsi_high": 55})
    assert trend[1].trades > 0
    assert mr[1].trades > 0
    assert trend[1].pnl != mr[1].pnl
