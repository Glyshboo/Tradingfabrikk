from __future__ import annotations

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
        "proposed_actions",
        "config_patch",
        "search_space_patch",
        "confidence",
        "warnings",
    }
