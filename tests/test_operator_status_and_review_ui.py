from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from apps.status_tool import _render_operator_view
from apps.review_server import ReviewHandler
from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ReviewQueue


def test_status_operator_view_explains_pending_zero_with_incubation(tmp_path):
    registry = CandidateRegistry(str(tmp_path / "registry.json"))
    registry.register("cand_1", 1.0, {"symbol": "BTCUSDT", "regime": "trend"})
    registry.transition("cand_1", "config_generated")
    registry.transition("cand_1", "backtest_pass")
    registry.transition("cand_1", "paper_smoke_running")

    status = {
        "mode": "paper",
        "state": "running",
        "ts": 1700000000,
        "ws_status": {"market": "healthy", "user": "healthy"},
        "safe_pause": False,
        "reduce_only": False,
        "review_queue_size": 0,
        "candidate_registry": registry.report(),
        "no_trade_diagnostics": {"reason": "none"},
    }
    out = _render_operator_view(status, research_last_run=None, status_file=tmp_path / "status.json")
    assert "No candidates are ready for review yet" in out


def test_review_api_returns_registry_counts(tmp_path):
    queue = ReviewQueue(str(tmp_path / "review_queue.json"))
    registry = CandidateRegistry(str(tmp_path / "registry.json"))
    registry.register("cand_2", 1.0, {"symbol": "BTCUSDT", "regime": "trend"})
    registry.transition("cand_2", "config_generated")
    registry.transition("cand_2", "backtest_pass")
    queue.enqueue({"id": "cand_2", "created_ts": 1.0})

    ReviewHandler.queue = queue
    ReviewHandler.registry = registry

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReviewHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/candidates", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["registry_total"] == 1
        assert payload["registry_counts"]["backtest_pass"] == 1
        assert len(payload["pending"]) == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)
