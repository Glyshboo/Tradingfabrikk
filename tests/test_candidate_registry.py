from packages.research.candidate_registry import CandidateRegistry


def test_candidate_registry_register_and_transition(tmp_path):
    reg = CandidateRegistry(path=str(tmp_path / "registry.json"))
    reg.register("cand_1", 1.2, {"symbol": "BTCUSDT", "candidate_type": "config"})
    reg.transition("cand_1", "config_generated")
    reg.transition("cand_1", "backtest_pass")
    report = reg.report()
    assert report["total"] == 1
    assert report["counts"]["backtest_pass"] == 1
    assert len(report["latest"]) == 1


def test_candidate_registry_blocks_backward_transition(tmp_path):
    reg = CandidateRegistry(path=str(tmp_path / "registry.json"))
    reg.register("cand_1", 1.2, {"symbol": "BTCUSDT"})
    reg.transition("cand_1", "ready_for_review")
    try:
        reg.transition("cand_1", "idea_proposed")
    except ValueError as exc:
        assert "invalid backward transition" in str(exc)
    else:
        raise AssertionError("expected ValueError for backward transition")


def test_candidate_registry_persists_llm_research_fields(tmp_path):
    reg = CandidateRegistry(path=str(tmp_path / "registry.json"))
    reg.register(
        "llm_1",
        0.0,
        {
            "symbol": "MULTI",
            "candidate_type": "config",
            "strategy_profile_patch": {"BTCUSDT": {"RANGE": [["RangeMR", "cand"]]}},
            "search_space_patch": {"strategy_configs": {"RangeMR": ["cand"]}},
            "research_fields": {
                "edge_hypothesis": "Netto edge i range-reversion",
                "failure_mode_target": "trend breakouts",
            },
        },
    )
    row = reg.get("llm_1")
    assert row is not None
    assert row["artifacts"]["research_fields"]["edge_hypothesis"] == "Netto edge i range-reversion"


def test_candidate_registry_persists_onboarding_artifacts(tmp_path):
    reg = CandidateRegistry(path=str(tmp_path / "registry.json"))
    reg.register(
        "cand_trust",
        0.8,
        {
            "symbol": "BTCUSDT",
            "onboarding_assessment": {
                "trust_score": 0.66,
                "complexity_summary": {"filter_complexity": 1, "exit_complexity": 0, "mutation_distance": 0.1},
                "novelty_summary": {"novelty_class": "minor_tweak"},
            },
            "mutation_trace": {"changed_keys": ["atr_stop_mult"]},
            "mutation_source_id": "parent_1",
        },
    )

    row = reg.get("cand_trust")
    assert row is not None
    assert row["trust_score"] == 0.66
    assert row["artifacts"]["complexity_summary"]["filter_complexity"] == 1
    assert row["artifacts"]["mutation_source_id"] == "parent_1"
