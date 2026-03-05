from pathlib import Path

from packages.profiles.symbol_profile import SymbolProfile
from packages.research.optimizer import ResearchOptimizer


def test_random_search_creates_candidates_per_symbol(tmp_path):
    out_dir = tmp_path / "candidates"
    optimizer = ResearchOptimizer(out_dir=str(out_dir), seed=1)
    search_space = {
        "atr_stop_mult": [2.0],
        "time_stop_bars": [12],
        "base_confidence": [0.58],
        "bars": 60,
    }

    ranking = optimizer.random_search(
        search_space,
        symbols=["BTCUSDT", "ETHUSDT"],
        regimes=["TREND_UP"],
        strategy_families=["TrendCore"],
        samples=1,
    )

    assert set(ranking.keys()) == {"BTCUSDT:TREND_UP", "ETHUSDT:TREND_UP"}
    assert (out_dir / "btcusdt_trend_up_trendcore_0.json").exists()
    assert (out_dir / "ethusdt_trend_up_trendcore_0.json").exists()
    assert Path(out_dir / "ranking.json").exists()
    assert Path(out_dir / "ranking.yaml").exists()


def test_random_search_score_changes_with_cost_model(tmp_path):
    search_space = {
        "atr_stop_mult": [2.0],
        "time_stop_bars": [12],
        "base_confidence": [0.58],
        "bars": 80,
    }

    low_cost_optimizer = ResearchOptimizer(out_dir=str(tmp_path / "low"), seed=2)
    low_cost_ranking = low_cost_optimizer.random_search(
        search_space,
        symbols=["BTCUSDT"],
        regimes=["RANGE"],
        strategy_families=["TrendCore"],
        samples=1,
        symbol_profiles={"BTCUSDT": SymbolProfile(liquidity_signature=1.0, slippage_proxy=0.0)},
    )

    high_cost_optimizer = ResearchOptimizer(out_dir=str(tmp_path / "high"), seed=2)
    high_cost_ranking = high_cost_optimizer.random_search(
        search_space,
        symbols=["BTCUSDT"],
        regimes=["RANGE"],
        strategy_families=["TrendCore"],
        samples=1,
        symbol_profiles={"BTCUSDT": SymbolProfile(liquidity_signature=0.1, slippage_proxy=0.0012)},
    )

    low_score = low_cost_ranking["BTCUSDT:RANGE"][0]["score"]
    high_score = high_cost_ranking["BTCUSDT:RANGE"][0]["score"]
    assert high_score < low_score
