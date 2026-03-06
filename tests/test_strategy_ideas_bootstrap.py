from __future__ import annotations

from packages.research.strategy_ideas import StrategyIdeaLibrary


def test_strategy_idea_library_seeded_and_mapped():
    lib = StrategyIdeaLibrary("strategy_ideas")
    report = lib.report()
    assert report["total"] >= 20
    families = {row["family"] for row in report["implemented_plugins"]}
    assert "TrendCore" in families
    assert "RangeMR" in families
    assert len(report["strict_track_candidates"]) >= 1
    assert len(report["proposed_for_future_implementation"]) >= 1


def test_strategy_idea_rank_for_symbol_regime():
    lib = StrategyIdeaLibrary("strategy_ideas")
    rows = lib.rank_for_symbol_regime("BTCUSDT", "TREND_UP", limit=3)
    assert len(rows) == 3
    assert rows[0]["score"] >= rows[-1]["score"]


def test_strategy_idea_manifest_and_schema_validation():
    lib = StrategyIdeaLibrary("strategy_ideas")
    validation = lib.validation_report()
    assert validation["valid"] is True
    assert validation["manifest"]["valid"] is True
    assert validation["valid_count"] == lib.report()["total"]


def test_mapping_is_conservative():
    lib = StrategyIdeaLibrary("strategy_ideas")
    report = lib.report()
    implemented_ids = {row["id"] for row in report["implemented_plugins"]}
    assert "idea_donchian_breakout_trend" not in implemented_ids
    assert "idea_trend_ema_crossover" in implemented_ids
