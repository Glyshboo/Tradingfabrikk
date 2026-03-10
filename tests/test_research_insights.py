from packages.research.insights import build_family_filter_exit_attribution, summarize_no_trade_intelligence


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
    }

    summary = summarize_no_trade_intelligence(payload)

    assert summary["total_no_trade_events"] == 4
    assert summary["top_reasons"][0][0] == "entry_no_signal"
    assert summary["family_patterns"][0]["family"] == "RangeMR"
