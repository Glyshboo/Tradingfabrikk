from packages.core.models import Regime, StrategySignal
from packages.selector.performance_memory import PerformanceMemory
from packages.selector.strategy_selector import StrategySelector


def test_selector_includes_learned_adjustment_and_uncertainty():
    mem = PerformanceMemory({"pnl_scale": 0.1, "max_adjustment": 0.1})
    for _ in range(5):
        mem.update("BTCUSDT", "TREND_UP", "TrendCore", "default", pnl=0.15, source="paper")

    selector = StrategySelector(base_edge={"TrendCore": 0.1}, performance_memory=mem)
    signal = StrategySignal("BTCUSDT", "BUY", 0.8, None, None, "x")
    decision = selector.select(
        "BTCUSDT",
        Regime.TREND_UP,
        [("TrendCore", "default", signal)],
        {"spread": 0.0, "slippage": 0.0, "funding": 0.0},
        exposure_penalty=0.0,
    )

    comp = decision.score_components["TrendCore:default"]
    assert comp["learned_adjustment"] > 0
    assert comp["uncertainty_penalty"] >= 0


def test_selector_without_memory_keeps_neutral_learned_component():
    selector = StrategySelector(base_edge={"TrendCore": 0.1})
    signal = StrategySignal("BTCUSDT", "BUY", 0.8, None, None, "x")
    decision = selector.select(
        "BTCUSDT",
        Regime.TREND_UP,
        [("TrendCore", "default", signal)],
        {"spread": 0.01, "slippage": 0.0, "funding": 0.0},
        exposure_penalty=0.0,
    )

    comp = decision.score_components["TrendCore:default"]
    assert comp["learned_adjustment"] == 0.0
    assert comp["uncertainty_penalty"] == 0.0
