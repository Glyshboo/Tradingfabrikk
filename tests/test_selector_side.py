from packages.core.models import MarketSnapshot, Regime
from packages.selector.strategy_selector import StrategySelector
from packages.strategies.trend_core import TrendCore


def test_selector_keeps_signal_side():
    selector = StrategySelector({"TrendCore": 0.1})
    strat = TrendCore()
    snap = MarketSnapshot(symbol="BTCUSDT", price=100, bid=99.9, ask=100.1, atr=1.0, rsi=60)
    sig = strat.generate(snap, Regime.TREND_UP, {"base_confidence": 0.58, "atr_stop_mult": 2.0})
    rec = selector.select(
        "BTCUSDT",
        Regime.TREND_UP,
        [("TrendCore", "tc_safe", sig)],
        {"spread": 0.0, "slippage": 0.0, "funding": 0.0},
        0.0,
    )
    assert rec is not None
    assert rec.selected_side == "BUY"
