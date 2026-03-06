from __future__ import annotations

from packages.llm.research import LLMResearchService


def test_provider_alias_resolution():
    svc = LLMResearchService({"provider": "codex", "fallback_provider": "claude"})
    assert svc._resolve_provider_name("codex") == "openai"
    assert svc._resolve_provider_name("claude") == "anthropic"


def test_research_fallback_fail_closed(tmp_path):
    svc = LLMResearchService({"provider": "codex", "fallback_provider": "claude"}, out_dir=str(tmp_path))
    artifact = svc.research("test prompt", bundle={"x": 1})
    assert artifact["provider"] == "none"
    assert artifact["primary_provider"] == "openai"
    assert artifact["fallback_provider"] == "anthropic"
    assert artifact["auto_deploy"] is False
