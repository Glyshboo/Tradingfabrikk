import subprocess
import sys

from packages.research.candidate_registry import CandidateRegistry


def test_candidate_status_tool_requires_pair_for_transition(tmp_path):
    registry = tmp_path / "registry.json"
    CandidateRegistry(path=str(registry))

    proc = subprocess.run(
        [sys.executable, "-m", "apps.candidate_status_tool", "--registry", str(registry), "--transition-id", "cand_1"],
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert "required together" in (proc.stderr + proc.stdout)


def test_candidate_status_tool_blocks_live_approved_without_flag(tmp_path):
    registry = tmp_path / "registry.json"
    reg = CandidateRegistry(path=str(registry))
    reg.register("cand_1", 1.0, {"symbol": "BTCUSDT"})
    reg.transition("cand_1", "backtest_pass")
    reg.transition("cand_1", "paper_pass")
    reg.transition("cand_1", "ready_for_review")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.candidate_status_tool",
            "--registry",
            str(registry),
            "--transition-id",
            "cand_1",
            "--transition-state",
            "live_approved",
        ],
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert "Refusing live_approved transition" in (proc.stderr + proc.stdout)
