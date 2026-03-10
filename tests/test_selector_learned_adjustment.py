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


def test_selector_cold_start_family_bias_tapers_with_samples():
    mem = PerformanceMemory({"pnl_scale": 0.1})
    selector = StrategySelector(
        base_edge={"BreakoutRetest": 0.035},
        performance_memory=mem,
        cold_start_bias={"BreakoutRetest": 0.008},
        cold_start_max_samples=8,
    )
    signal = StrategySignal("BTCUSDT", "BUY", 0.6, None, None, "x")

    decision_fresh = selector.select(
        "BTCUSDT",
        Regime.TREND_UP,
        [("BreakoutRetest", "default", signal)],
        {"spread": 0.0, "slippage": 0.0, "funding": 0.0},
        exposure_penalty=0.0,
    )

    for _ in range(10):
        mem.update("BTCUSDT", "TREND_UP", "BreakoutRetest", "default", pnl=0.02, source="paper")

    decision_mature = selector.select(
        "BTCUSDT",
        Regime.TREND_UP,
        [("BreakoutRetest", "default", signal)],
        {"spread": 0.0, "slippage": 0.0, "funding": 0.0},
        exposure_penalty=0.0,
    )

    fresh = decision_fresh.score_components["BreakoutRetest:default"]
    mature = decision_mature.score_components["BreakoutRetest:default"]
    assert fresh["family_cold_start_adjustment"] > mature["family_cold_start_adjustment"]
    assert fresh["static_base_edge"] == 0.035
