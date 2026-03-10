from __future__ import annotations

from packages.llm.providers import LLMResponse
from packages.llm.research import LLMResearchService, LLMBudgetTracker


def test_budget_tracker_enforces_limits(tmp_path):
    tracker = LLMBudgetTracker(str(tmp_path / "budget.json"))
    for _ in range(2):
        tracker.record_call("openai", True)
    ok, status = tracker.allow({"max_calls_per_day": 2, "max_calls_per_week": 10})
    assert ok is False
    assert status["used_day"] == 2


def test_llm_research_structured_fail_closed(tmp_path):
    svc = LLMResearchService(
        {"provider": "codex", "fallback_provider": "claude", "budgets": {"max_calls_per_day": 1, "max_calls_per_week": 1}},
        out_dir=str(tmp_path / "llm"),
    )
    artifact = svc.research("prompt", bundle={"x": 1})
    assert "structured" in artifact
    assert set(artifact["structured"].keys()) == {
        "summary",
        "diagnosis",
        "edge_hypothesis",
        "failure_mode_target",
        "expected_market_regime",
        "proposed_actions",
        "config_patch",
        "strategy_profile_patch",
        "search_space_patch",
        "validation_plan",
        "risk_to_overfit",
        "confidence",
        "warnings",
    }


def test_llm_research_normalize_fail_closed_on_missing_required_fields(tmp_path):
    svc = LLMResearchService({"provider": "codex", "fallback_provider": "claude"}, out_dir=str(tmp_path / "llm"))
    response = LLMResponse(provider="openai", summary="", raw_text='{"summary":"x"}')
    structured = svc._normalize(response)
    assert structured["summary"] == ""
    assert any("missing_required_keys" in w for w in structured["warnings"])
