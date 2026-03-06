from __future__ import annotations

import json
from pathlib import Path

from apps.llm_research_runner import _compact_research_bundle


def test_compact_research_bundle_includes_strategy_idea_context(tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_text(
        json.dumps(
            {
                "symbols": ["BTCUSDT"],
                "current_regime": {"BTCUSDT": "TREND_UP"},
                "last_decision": {"blocked_reason": None, "score_components": {}},
            }
        ),
        encoding="utf-8",
    )

    bundle = _compact_research_bundle(str(status_file), ideas_dir="strategy_ideas")
    strategy_library = bundle["strategy_idea_library"]

    assert strategy_library["summary"]["total"] >= 20
    assert strategy_library["summary"]["implemented_plugin_count"] >= 2
    assert "BTCUSDT:TREND_UP" in strategy_library["top_ranked_by_symbol_regime"]
    assert strategy_library["validation"]["valid"] is True
