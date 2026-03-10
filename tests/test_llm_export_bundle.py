from __future__ import annotations

import json

from packages.research.llm_export_bundle import ResearchBundleExporter


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_export_bundle_with_status_and_registry(tmp_path):
    status = tmp_path / "status.json"
    registry = tmp_path / "registry.json"
    engine_state = tmp_path / "engine_state.json"
    review_queue = tmp_path / "review_queue.json"
    out_dir = tmp_path / "llm_exports"

    _write_json(
        status,
        {
            "mode": "paper",
            "state": "running",
            "safe_pause": False,
            "reduce_only": False,
            "current_regime": {"BTCUSDT": "TREND_UP"},
            "last_decision": {"blocked_reason": None, "score_components": {"base_edge": 0.1}},
            "paper_candidate": {
                "challenger_evaluations": [
                    {"candidate_id": "cand_b", "challenger_pnl": -1.2, "symbol": "ETHUSDT", "regime": "RANGE"}
                ]
            },
            "no_trade_diagnostics": {
                "total_no_trade_events": 3,
                "reason_counts": {"blocked_by_filter:range_quality_gate": 2, "entry_no_signal": 1},
                "family_reason_counts": {"RangeMR": {"blocked_by_filter:range_quality_gate": 2}},
                "family_quality": {"RangeMR": {"observed": 2, "setup_quality_sum": 0.7}},
                "symbol_reason_counts": {"ETHUSDT": {"blocked_by_filter:range_quality_gate": 2}},
                "reason_outcome_stats": {
                    "blocked_by_filter:range_quality_gate": {"blocked": 2, "would_win": 0, "would_lose": 2}
                },
            },
        },
    )
    _write_json(
        registry,
        {
            "candidates": {
                "cand_a": {
                    "state": "paper_candidate_active",
                    "score": 0.81,
                    "strategy_family": "TrendCore",
                    "symbols": ["BTCUSDT"],
                    "regimes": ["TREND_UP"],
                    "meta": {"plausible": True, "recommendation": "keep_paper"},
                    "strategy_composition": {"entry_family": "TrendCore", "filter_pack": "trend_baseline", "filter_modules": ["trend_slope_gate"], "exit_pack": "atr_trail"},
                    "artifacts": {"oos_result": {"pnl": 12.4, "sharpe_like": 1.4}},
                    "updated_ts": 100,
                },
                "cand_b": {
                    "state": "validation_failed",
                    "score": 0.2,
                    "strategy_family": "RangeMR",
                    "symbols": ["ETHUSDT"],
                    "regimes": ["RANGE"],
                    "meta": {"plausible": False, "rejection_reasons": ["weak_or_negative_out_sample_pnl"]},
                    "strategy_composition": {"entry_family": "RangeMR", "filter_pack": "range_baseline", "filter_modules": ["range_quality_gate"], "exit_pack": "fixed_rr"},
                    "artifacts": {"oos_result": {"pnl": -2.1, "sharpe_like": -0.4}},
                    "updated_ts": 90,
                },
            }
        },
    )
    _write_json(
        engine_state,
        {
            "performance_memory_state": {
                "BTCUSDT|TREND_UP|TrendCore|tc_safe": {
                    "sample_count": 14,
                    "recent_pnl": 0.24,
                    "hit_rate": 0.62,
                    "avg_result": 0.2,
                    "challenger_relative": 0.1,
                }
            }
        },
    )
    _write_json(review_queue, {"queue": [], "history": []})

    exporter = ResearchBundleExporter(
        status_file=str(status),
        registry_file=str(registry),
        engine_state_file=str(engine_state),
        review_queue_file=str(review_queue),
        output_dir=str(out_dir),
    )

    report = exporter.export()

    assert report["output_dir"] == str(out_dir)
    assert (out_dir / "executive_summary.md").exists()
    assert (out_dir / "top_candidates.md").exists()
    assert (out_dir / "failure_report.md").exists()
    bundle = json.loads((out_dir / "research_bundle.json").read_text(encoding="utf-8"))
    assert bundle["mode_status_summary"]["mode"] == "paper"
    assert bundle["top_candidates"][0]["candidate_id"] == "cand_a"
    assert bundle["performance_memory_snapshot"]["total_cells"] == 1
    assert "family_filter_exit_attribution" in bundle
    assert "family_profiles" in bundle
    assert "quality_summaries" in bundle
    assert "no_trade_intelligence" in bundle


def test_export_bundle_handles_missing_inputs_fail_soft(tmp_path):
    out_dir = tmp_path / "llm_exports"
    exporter = ResearchBundleExporter(
        status_file=str(tmp_path / "missing_status.json"),
        registry_file=str(tmp_path / "missing_registry.json"),
        engine_state_file=str(tmp_path / "missing_engine_state.json"),
        review_queue_file=str(tmp_path / "missing_review_queue.json"),
        output_dir=str(out_dir),
    )

    report = exporter.export()
    bundle = json.loads((out_dir / "research_bundle.json").read_text(encoding="utf-8"))

    assert report["top_candidates"] == 0
    assert bundle["mode_status_summary"]["mode"] == "not available"
    assert len(bundle["important_sources"]) == 5


def test_research_bundle_json_has_stable_structure(tmp_path):
    registry = tmp_path / "registry.json"
    _write_json(registry, {"candidates": {}})

    exporter = ResearchBundleExporter(
        registry_file=str(registry),
        status_file=str(tmp_path / "status.json"),
        engine_state_file=str(tmp_path / "engine_state.json"),
        review_queue_file=str(tmp_path / "review.json"),
        output_dir=str(tmp_path / "llm_exports"),
    )
    exporter.export()

    bundle = json.loads((tmp_path / "llm_exports" / "research_bundle.json").read_text(encoding="utf-8"))
    expected_keys = {
        "generated_ts",
        "mode_status_summary",
        "current_regime_summary",
        "top_candidates",
        "candidate_state_counts",
        "recent_challenger_evaluations",
        "performance_memory_snapshot",
        "selector_summary",
        "top_failure_patterns",
        "family_filter_exit_attribution",
        "family_profiles",
        "quality_summaries",
        "no_trade_intelligence",
        "research_recommendations",
        "recent_research_rankings",
        "important_sources",
    }
    assert expected_keys.issubset(set(bundle.keys()))


def test_paste_to_llm_contains_required_blocks(tmp_path):
    registry = tmp_path / "registry.json"
    _write_json(registry, {"candidates": {}})

    exporter = ResearchBundleExporter(
        registry_file=str(registry),
        status_file=str(tmp_path / "status.json"),
        engine_state_file=str(tmp_path / "engine_state.json"),
        review_queue_file=str(tmp_path / "review.json"),
        output_dir=str(tmp_path / "llm_exports"),
    )
    exporter.export()

    paste = (tmp_path / "llm_exports" / "paste_to_llm.md").read_text(encoding="utf-8")
    assert "Systeminstruksjon til LLM" in paste
    assert "Eksplisitt mål" in paste
    assert "Executive summary" in paste
    assert "Top candidates" in paste
    assert "Failure patterns" in paste
    assert "Family/filter/exit attribution snapshot" in paste
    assert "Family profile snapshot" in paste
    assert "Quality diagnostics snapshot" in paste
    assert "No-trade intelligence snapshot" in paste
    assert "Påkrevd svarformat" in paste
    assert "## config_changes" in paste
    assert "## search_space_changes" in paste
    assert "## regime_or_selector_changes" in paste
    assert "## new_strategy_ideas" in paste
    assert "## requires_code" in paste
    assert "Unngå overfitting" in paste


def test_export_writes_llm_response_template_file(tmp_path):
    exporter = ResearchBundleExporter(
        registry_file=str(tmp_path / "registry.json"),
        status_file=str(tmp_path / "status.json"),
        engine_state_file=str(tmp_path / "engine_state.json"),
        review_queue_file=str(tmp_path / "review.json"),
        output_dir=str(tmp_path / "llm_exports"),
    )
    exporter.export()

    template = (tmp_path / "llm_exports" / "llm_response_template.md").read_text(encoding="utf-8")
    assert "# LLM Research Response" in template
    assert "## config_changes" in template
    assert "## search_space_changes" in template
    assert "## regime_or_selector_changes" in template
    assert "## new_strategy_ideas" in template
    assert "## requires_code" in template


def test_manual_workflow_doc_references_expected_files():
    doc = "docs/manual_llm_workflow.md"
    content = open(doc, encoding="utf-8").read()

    assert "runtime/llm_exports/paste_to_llm.md" in content
    assert "runtime/llm_exports/llm_response_template.md" in content
    assert "apps/export_research_bundle.py" in content
