from __future__ import annotations

from pathlib import Path

from packages.core.state_store import EngineStateStore
from packages.review.review_queue import ReviewQueue
from packages.risk.engine import RiskEngine
from packages.core.models import AccountState, OrderRequest


def test_engine_state_store_session_and_downtime(tmp_path: Path):
    store = EngineStateStore(str(tmp_path / "state.json"))
    s1 = store.register_startup()
    assert s1.downtime_sec == 0
    store.register_shutdown()
    s2 = store.register_startup()
    assert s2.downtime_sec >= 0


def test_review_queue_actions(tmp_path: Path):
    queue = ReviewQueue(str(tmp_path / "queue.json"))
    queue.enqueue({"id": "c1", "track": "fast"})
    assert len(queue.list_ready()) == 1
    out = queue.apply_action("c1", "approve_micro_live", "ok")
    assert out["action"] == "approve_micro_live"
    assert len(queue.list_ready()) == 0


def test_weekly_guard_trigger(tmp_path: Path):
    risk = RiskEngine(
        {
            "max_daily_loss": 100,
            "max_weekly_loss": 200,
            "max_drawdown_pct": 0.1,
            "max_total_exposure_notional": 100000,
            "max_open_positions": 5,
            "max_leverage": 5,
            "per_symbol_exposure_cap": {},
            "correlation_clusters": {},
        }
    )
    risk.weekly_pnl = -250
    account = AccountState(equity=1000, daily_pnl=0, positions={}, leverage=1.0, known=True)
    rr = risk.evaluate_order(OrderRequest(symbol="BTCUSDT", side="BUY", qty=0.01), account, {})
    assert rr.allowed is False
    assert rr.reason == "weekly_guard_triggered"


def test_candidate_registry_meta_update(tmp_path: Path):
    from packages.research.candidate_registry import CandidateRegistry

    reg = CandidateRegistry(str(tmp_path / "registry.json"))
    reg.register("c1", 1.0, {"symbol": "BTCUSDT", "regime": "RANGE"})
    reg.transition("c1", "config_generated")
    reg.update_meta("c1", meta_patch={"keep_paper": True}, artifacts_patch={"paper_smoke_result": {"status": "kept"}})
    rows = reg.list_by_state(["config_generated"])
    assert rows[0]["meta"]["keep_paper"] is True
    assert rows[0]["artifacts"]["paper_smoke_result"]["status"] == "kept"
