from packages.core.models import Regime, StrategySignal
from packages.profiles.symbol_profile import SymbolProfile
from packages.selector.strategy_selector import StrategySelector


def test_selector_score_degrades_with_exposure_and_correlation():
    selector = StrategySelector(base_edge={"TrendCore": 0.1})
    signal = StrategySignal("BTCUSDT", "BUY", 0.8, None, None, "x")
    d_low = selector.select(
        "BTCUSDT",
        Regime.TREND_UP,
        [("TrendCore", "default", signal)],
        {"spread": 0.001, "slippage": 0.0, "funding": 0.0},
        exposure_penalty=0.0,
        current_positions={},
        symbol_profile=SymbolProfile(liquidity_signature=1.0),
    )
    d_high = selector.select(
        "BTCUSDT",
        Regime.TREND_UP,
        [("TrendCore", "default", signal)],
        {"spread": 0.01, "slippage": 0.005, "funding": 0.001},
        exposure_penalty=0.2,
        current_positions={"ETHUSDT": 1.0, "SOLUSDT": 1.0},
        symbol_profile=SymbolProfile(liquidity_signature=0.2),
    )
    assert d_high.score_breakdown["TrendCore:default"] < d_low.score_breakdown["TrendCore:default"]
