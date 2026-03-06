from __future__ import annotations

from packages.research.strategy_ideas import StrategyIdeaLibrary


def test_strategy_idea_library_seeded_and_mapped():
    lib = StrategyIdeaLibrary("strategy_ideas")
    report = lib.report()
    assert report["total"] >= 8
    families = {row["family"] for row in report["implemented_plugins"]}
    assert "TrendCore" in families
    assert "RangeMR" in families
    assert len(report["strict_track_candidates"]) >= 1


def test_strategy_idea_rank_for_symbol_regime():
    lib = StrategyIdeaLibrary("strategy_ideas")
    rows = lib.rank_for_symbol_regime("BTCUSDT", "TREND_UP", limit=3)
    assert len(rows) == 3
    assert rows[0]["score"] >= rows[-1]["score"]
