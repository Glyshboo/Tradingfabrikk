from __future__ import annotations

import sys

from apps.review_runner import main as review_main
from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ReviewQueue


def test_review_actions_drive_runtime_states(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = CandidateRegistry()
    queue = ReviewQueue()
    registry.register("cand_1", 0.4, {"symbols": ["BTCUSDT"]})
    registry.transition("cand_1", "ready_for_review")
    queue.enqueue({"id": "cand_1", "track": "fast", "type": "config", "created_ts": 1})

    monkeypatch.setattr(sys, "argv", ["review_runner", "--action", "keep_paper", "--candidate-id", "cand_1"])
    review_main()
    assert registry.get("cand_1")["state"] == "paper_candidate_active"

    queue.enqueue({"id": "cand_1", "track": "fast", "type": "config", "created_ts": 2})
    monkeypatch.setattr(sys, "argv", ["review_runner", "--action", "hold", "--candidate-id", "cand_1"])
    review_main()
    assert registry.get("cand_1")["state"] == "paper_candidate_paused"
