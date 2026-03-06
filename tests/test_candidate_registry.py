import pytest

from packages.research.candidate_registry import CandidateRegistry


def test_candidate_registry_register_and_transition(tmp_path):
    reg = CandidateRegistry(path=str(tmp_path / "registry.json"))
    reg.register("cand_1", 1.2, {"symbol": "BTCUSDT"})
    reg.transition("cand_1", "backtest_pass")
    reg.transition("cand_1", "paper_pass")
    report = reg.report()
    assert report["total"] == 1
    assert report["counts"]["paper_pass"] == 1


def test_candidate_registry_rejects_invalid_transition(tmp_path):
    reg = CandidateRegistry(path=str(tmp_path / "registry.json"))
    reg.register("cand_1", 1.2, {"symbol": "BTCUSDT"})
    with pytest.raises(ValueError):
        reg.transition("cand_1", "live_approved")


def test_candidate_registry_stores_paper_eval_and_auto_transitions(tmp_path):
    reg = CandidateRegistry(path=str(tmp_path / "registry.json"))
    reg.register("cand_1", 1.2, {"symbol": "BTCUSDT"})
    reg.transition("cand_1", "backtest_pass")
    reg.store_paper_evaluation("cand_1", passed=True, pnl=123.0, max_drawdown=12.0, notes="ok")
    report = reg.report()
    assert report["counts"]["paper_pass"] == 1
    assert report["paper_passed"] == 1
