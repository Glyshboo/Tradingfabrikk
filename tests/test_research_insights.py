from packages.research.insights import (
    build_family_filter_exit_attribution,
    build_family_profiles,
    build_quality_summary,
    summarize_no_trade_intelligence,
)


def test_family_filter_exit_attribution_builds_summaries():
    candidates = [
        {
            "strategy_family": "TrendCore",
            "research_score": 1.2,
            "oos_result": {"pnl": 2.0},
            "strategy_composition": {"filter_pack": "trend_baseline", "filter_modules": ["trend_slope_gate"], "exit_pack": "atr_trail"},
        },
        {
            "strategy_family": "TrendCore",
            "research_score": 0.2,
            "oos_result": {"pnl": -1.0},
            "strategy_composition": {"filter_pack": "safe", "filter_modules": [], "exit_pack": "passthrough"},
        },
    ]
    summary = build_family_filter_exit_attribution(candidates, {})

    assert summary["family_summary"]
    assert summary["filter_pack_summary"]
    assert summary["exit_pack_summary"]


def test_no_trade_summary_includes_family_patterns():
    payload = {
        "total_no_trade_events": 4,
        "reason_counts": {"entry_no_signal": 3, "blocked_by_filter:range_quality_gate": 1},
        "family_reason_counts": {"RangeMR": {"blocked_by_filter:range_quality_gate": 1}},
        "family_quality": {"RangeMR": {"observed": 2, "setup_quality_sum": 0.4}},
        "symbol_reason_counts": {"BTCUSDT": {"entry_no_signal": 2}},
        "reason_outcome_stats": {"entry_no_signal": {"blocked": 2, "would_win": 0, "would_lose": 2}},
    }

    summary = summarize_no_trade_intelligence(payload)

    assert summary["total_no_trade_events"] == 4
    assert summary["top_reasons"][0][0] == "entry_no_signal"
    assert summary["family_patterns"][0]["family"] == "RangeMR"
    assert summary["symbol_patterns"][0]["symbol"] == "BTCUSDT"
    assert summary["gate_usefulness"][0]["assessment"] == "protective"


def test_quality_and_family_profile_generation():
    candidates = [
        {
            "strategy_family": "TrendCore",
            "symbol": "BTCUSDT",
            "regime": "TREND_UP",
            "research_score": 1.0,
            "oos_result": {"pnl": 2.0, "sharpe_like": 1.2},
            "challenger_result": {"avg_pnl": 0.5},
            "strategy_composition": {"filter_pack": "trend_baseline", "exit_pack": "atr_trail"},
        }
    ]
    attribution = build_family_filter_exit_attribution(candidates, {})
    no_trade = summarize_no_trade_intelligence({"family_reason_counts": {"TrendCore": {"entry_no_signal": 1}}, "family_quality": {"TrendCore": {"observed": 1, "setup_quality_sum": 0.3}}})

    quality = build_quality_summary(candidates, no_trade)
    profiles = build_family_profiles(candidates, attribution, no_trade, {"top_cells": []})

    assert quality["market_quality"]["market_quality_score"] > 0
    assert quality["setup_quality"]["setup_quality_score"] > 0
    assert quality["symbol_quality"]["symbol_quality_score"] > 0
    assert "TrendCore" in profiles["family_profiles"]
    assert "preferred_regimes" in profiles["family_profiles"]["TrendCore"]
