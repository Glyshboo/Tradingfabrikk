from pathlib import Path

from packages.backtest.engine import BacktestResult
from packages.profiles.symbol_profile import SymbolProfile
from packages.research.optimizer import ResearchOptimizer


def test_random_search_creates_candidates_per_symbol(tmp_path, monkeypatch):
    out_dir = tmp_path / "candidates"
    optimizer = ResearchOptimizer(out_dir=str(out_dir), seed=1)
    search_space = {
        "atr_stop_mult": [2.0],
        "time_stop_bars": [12],
        "base_confidence": [0.58],
        "bars": 60,
    }

    synthetic_rows = [[i, str(100 + i - 0.3), str(100 + i + 0.8), str(100 + i - 0.8), str(100 + i)] for i in range(80)]
    from packages.data.data_manager import DataManager

    monkeypatch.setattr(DataManager, "_download_klines", lambda *args, **kwargs: synthetic_rows)

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


def test_score_prefers_stronger_out_of_sample_result():
    optimizer = ResearchOptimizer(seed=7)
    thresholds = {}
    high_oos = optimizer._evaluate_candidate(
        in_sample=BacktestResult(trades=12, pnl=8.0, sharpe_like=1.6, gross_pnl=10.5, total_cost=1.2, max_drawdown=1.1, turnover=600),
        out_sample=BacktestResult(trades=10, pnl=6.0, sharpe_like=1.4, gross_pnl=7.0, total_cost=0.9, max_drawdown=1.0, turnover=500),
        out_sample_no_cost=BacktestResult(trades=10, pnl=6.8, sharpe_like=1.6, gross_pnl=7.8, total_cost=0.0, max_drawdown=0.9, turnover=500),
        bars=120,
        cfg={"base_confidence": 0.58},
        thresholds=thresholds,
    )
    weak_oos = optimizer._evaluate_candidate(
        in_sample=BacktestResult(trades=14, pnl=10.0, sharpe_like=1.9, gross_pnl=12.0, total_cost=1.1, max_drawdown=1.1, turnover=620),
        out_sample=BacktestResult(trades=10, pnl=0.3, sharpe_like=0.12, gross_pnl=1.8, total_cost=1.5, max_drawdown=1.7, turnover=540),
        out_sample_no_cost=BacktestResult(trades=10, pnl=1.9, sharpe_like=0.4, gross_pnl=1.9, total_cost=0.0, max_drawdown=1.5, turnover=540),
        bars=120,
        cfg={"base_confidence": 0.58},
        thresholds=thresholds,
    )

    assert high_oos["plausible"] is True
    assert weak_oos["score"] < high_oos["score"]


def test_minimum_requirements_filter_marks_candidate_not_plausible():
    optimizer = ResearchOptimizer(seed=9)
    rejected = optimizer._evaluate_candidate(
        in_sample=BacktestResult(trades=2, pnl=4.0, sharpe_like=1.0, gross_pnl=4.8, total_cost=0.8, max_drawdown=0.6, turnover=9000),
        out_sample=BacktestResult(trades=1, pnl=-1.0, sharpe_like=-0.4, gross_pnl=0.8, total_cost=0.9, max_drawdown=2.0, turnover=20000),
        out_sample_no_cost=BacktestResult(trades=1, pnl=0.4, sharpe_like=0.1, gross_pnl=0.4, total_cost=0.0, max_drawdown=1.8, turnover=20000),
        bars=50,
        cfg={"base_confidence": 0.9},
        thresholds={"max_base_confidence": 0.75},
    )

    assert rejected["plausible"] is False
    assert "insufficient_out_sample_trades" in rejected["rejection_reasons"]
    assert "weak_or_negative_out_sample_pnl" in rejected["rejection_reasons"]


def test_random_search_score_changes_with_cost_model(tmp_path, monkeypatch):
    search_space = {
        "atr_stop_mult": [2.0],
        "time_stop_bars": [12],
        "base_confidence": [0.58],
        "bars": 80,
    }

    synthetic_rows = [[i, str(100 + i - 0.3), str(100 + i + 0.8), str(100 + i - 0.8), str(100 + i)] for i in range(120)]
    from packages.data.data_manager import DataManager

    monkeypatch.setattr(DataManager, "_download_klines", lambda *args, **kwargs: synthetic_rows)

    low_cost_optimizer = ResearchOptimizer(out_dir=str(tmp_path / "low"), seed=2)
    low_cost_ranking = low_cost_optimizer.random_search(
        search_space,
        symbols=["BTCUSDT"],
        regimes=["RANGE"],
        strategy_families=["TrendCore"],
        samples=1,
        start_ts=123,
        symbol_profiles={"BTCUSDT": SymbolProfile(liquidity_signature=1.0, slippage_proxy=0.0)},
    )

    high_cost_optimizer = ResearchOptimizer(out_dir=str(tmp_path / "high"), seed=2)
    high_cost_ranking = high_cost_optimizer.random_search(
        search_space,
        symbols=["BTCUSDT"],
        regimes=["RANGE"],
        strategy_families=["TrendCore"],
        samples=1,
        start_ts=123,
        symbol_profiles={"BTCUSDT": SymbolProfile(liquidity_signature=0.1, slippage_proxy=0.0012)},
    )

    low_score = low_cost_ranking["BTCUSDT:RANGE"][0]["score"]
    high_score = high_cost_ranking["BTCUSDT:RANGE"][0]["score"]
    assert high_score < low_score


def test_sampling_supports_new_entry_families() -> None:
    optimizer = ResearchOptimizer(seed=11)
    space = {
        "base_confidence": [0.58],
        "br_min_range_compression": [0.2],
        "tp_min_trend_slope": [0.0005],
        "fbf_min_failed_breakout_distance_atr": [0.18],
    }

    breakout = optimizer._sample_strategy_config("BreakoutRetest", space)
    pullback = optimizer._sample_strategy_config("TrendPullback", space)
    fade = optimizer._sample_strategy_config("FailedBreakoutFade", space)

    assert "min_reclaim_distance_atr" in breakout
    assert "max_pullback_distance_atr" in pullback
    assert "min_failed_breakout_distance_atr" in fade
