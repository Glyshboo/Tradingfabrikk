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
            "config_patch": {"strategy_configs": {"RangeMR": {"cand": {"base_confidence": 0.6}}}},
            "search_space_patch": {"strategy_configs": {"RangeMR": ["cand"]}},
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
    ok, errors, _ = validate_llm_candidate_payload(cfg, {"config_patch": {"risk": {"max_leverage": 50}}})
    assert ok is False
    assert any("unsupported_patch_keys" in e for e in errors)
