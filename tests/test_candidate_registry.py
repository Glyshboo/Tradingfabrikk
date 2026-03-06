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
