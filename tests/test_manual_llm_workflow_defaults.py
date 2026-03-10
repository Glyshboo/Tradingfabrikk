from __future__ import annotations

from pathlib import Path

import yaml

from apps.llm_research_runner import run_llm_research


def test_active_config_disables_internal_llm_by_default():
    cfg = yaml.safe_load(Path("configs/active.yaml").read_text(encoding="utf-8"))

    assert cfg["llm_research"]["enabled"] is False
    assert cfg["auto_research"]["llm"]["enabled"] is False


def test_llm_research_runner_returns_manual_workflow_message_when_disabled(capsys):
    result = run_llm_research(config_path="configs/active.yaml")

    assert result["skipped"] == "llm_research_disabled"
    assert "paste_to_llm.md" in result["message"]
    assert "manual workflow" in result["message"]

    out = capsys.readouterr().out
    assert "legacy/optional" in out
    assert "paste_to_llm.md" in out


def test_manual_workflow_docs_reference_export_prompt_file():
    readme = Path("README.md").read_text(encoding="utf-8")
    workflow_doc = Path("docs/manual_llm_workflow.md").read_text(encoding="utf-8")

    assert "runtime/llm_exports/paste_to_llm.md" in readme
    assert "standard" in workflow_doc.lower()
    assert "runtime/llm_exports/paste_to_llm.md" in workflow_doc
    assert "Codex" in workflow_doc
