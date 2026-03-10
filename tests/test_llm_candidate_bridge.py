from __future__ import annotations

from packages.research.candidate_bridge import validate_llm_candidate_payload


def test_llm_candidate_bridge_validates_safe_patch():
    cfg = {
        "symbols": ["BTCUSDT"],
        "strategy_configs": {"RangeMR": {"rmr_safe": {}}},
        "strategy_profiles": {"BTCUSDT": {"RANGE": [["RangeMR", "rmr_safe"]]}},
    }
    ok, errors, normalized = validate_llm_candidate_payload(
        cfg,
        {
            "summary": "Netto edge i trend-regime med lav funding-drag.",
            "diagnosis": "Dagens range-innstillinger blir for defensive i trend.",
            "edge_hypothesis": "Trend continuation entry etter pullback gir robust netto-edge.",
            "failure_mode_target": "Stop-run i lav likviditet rundt funding-reset.",
            "expected_market_regime": "TREND_UP med moderat volatilitet",
            "validation_plan": "Backtest 18m + OOS 6m + paper smoke med slippage stress.",
            "risk_to_overfit": "Middels; begrens parametere og bruk walk-forward.",
            "proposed_actions": ["config tweak: høyere trend-threshold"],
            "confidence": 0.62,
            "config_patch": {"strategy_configs": {"RangeMR": {"cand": {"base_confidence": 0.6}}}},
            "search_space_patch": {"strategy_configs": {"RangeMR": ["cand"]}},
            "warnings": ["manual_review_required"],
        },
    )
    assert ok is True
    assert errors == []
    assert normalized["config_patch"]["strategy_configs"]["RangeMR"]["cand"]["base_confidence"] == 0.6


def test_llm_candidate_bridge_fail_closed_on_unsafe_patch():
    cfg = {
        "symbols": ["BTCUSDT"],
        "strategy_configs": {"RangeMR": {"rmr_safe": {}}},
        "strategy_profiles": {"BTCUSDT": {"RANGE": [["RangeMR", "rmr_safe"]]}},
    }
    ok, errors, _ = validate_llm_candidate_payload(
        cfg,
        {
            "summary": "x",
            "diagnosis": "y",
            "edge_hypothesis": "z",
            "failure_mode_target": "f",
            "expected_market_regime": "RANGE",
            "validation_plan": "plan",
            "risk_to_overfit": "high",
            "proposed_actions": ["config tweak"],
            "confidence": 0.4,
            "config_patch": {"risk": {"max_leverage": 50}},
        },
    )
    assert ok is False
    assert any("unsupported_patch_keys" in e for e in errors)


def test_llm_candidate_bridge_requires_extended_research_fields():
    cfg = {"symbols": ["BTCUSDT"], "strategy_configs": {}, "strategy_profiles": {}}
    ok, errors, _ = validate_llm_candidate_payload(
        cfg,
        {
            "summary": "",
            "diagnosis": "",
            "config_patch": {"strategy_configs": {"RangeMR": {"cand": {"base_confidence": 0.55}}}},
            "proposed_actions": [],
            "confidence": 1.2,
        },
    )
    assert ok is False
    assert "missing_or_invalid_edge_hypothesis" in errors
    assert "missing_or_invalid_proposed_actions" in errors
    assert "confidence_out_of_range" in errors
