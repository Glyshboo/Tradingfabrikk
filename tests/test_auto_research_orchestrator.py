from __future__ import annotations

import json

from packages.research.auto_orchestrator import AutoResearchOrchestrator


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_schedule_trigger_runs_deterministic(tmp_path):
    status = tmp_path / "status.json"
    engine = tmp_path / "engine_state.json"
    state = tmp_path / "auto_state.json"
    _write_json(status, {"current_regime": {"BTCUSDT": "RANGE"}, "risk_caps_status": {"daily_pnl": 0}})
    _write_json(engine, {"paper_trade_history": [{}] * 10, "strategy_performance_history": []})

    calls = []

    def deterministic_runner(reasons, context):
        calls.append((reasons, context))
        return {"failed": False, "generated_candidates": 3}

    orch = AutoResearchOrchestrator(
        cfg={
            "mode": "paper",
            "triggers": {
                "research_schedule_hours": 1,
                "min_paper_trades_before_research": 1,
                "cooldown_hours": 0,
            },
            "llm": {"enabled": False, "run_after_deterministic": False},
        },
        status_file=str(status),
        engine_state_file=str(engine),
        state_file=str(state),
        deterministic_runner=deterministic_runner,
        llm_runner=None,
        now_fn=lambda: 2000,
    )

    report = orch.run_once()
    assert report["triggered"] is True
    assert "schedule" in report["reasons"]
    assert calls


def test_performance_drop_trigger(tmp_path):
    status = tmp_path / "status.json"
    engine = tmp_path / "engine_state.json"
    state = tmp_path / "auto_state.json"
    now = 5000
    _write_json(status, {"current_regime": {"BTCUSDT": "RANGE"}, "risk_caps_status": {"daily_pnl": -200}})
    _write_json(
        engine,
        {
            "paper_trade_history": [{}] * 15,
            "strategy_performance_history": [{"ts": now - 100, "blocked": True} for _ in range(12)],
        },
    )

    orch = AutoResearchOrchestrator(
        cfg={
            "mode": "paper",
            "risk": {"max_daily_loss": 300},
            "triggers": {
                "performance_drop_window_hours": 12,
                "performance_drop_threshold": -100,
                "min_performance_observations": 10,
                "min_paper_trades_before_research": 8,
                "cooldown_hours": 0,
            },
            "llm": {"enabled": False, "run_after_deterministic": False},
        },
        status_file=str(status),
        engine_state_file=str(engine),
        state_file=str(state),
        deterministic_runner=lambda *_: {"failed": False},
        llm_runner=None,
        now_fn=lambda: now,
    )

    report = orch.run_once()
    assert report["triggered"] is True
    assert "performance_drop" in report["reasons"]


def test_cooldown_rate_limit_blocks_spam(tmp_path):
    status = tmp_path / "status.json"
    engine = tmp_path / "engine_state.json"
    state = tmp_path / "auto_state.json"
    _write_json(status, {"current_regime": {"BTCUSDT": "RANGE"}, "risk_caps_status": {"daily_pnl": 0}})
    _write_json(engine, {"paper_trade_history": [{}] * 10, "strategy_performance_history": []})
    _write_json(state, {"last_run_ts": 1000, "last_regimes": {"BTCUSDT": "RANGE"}, "history": []})

    called = {"count": 0}

    def deterministic_runner(*_):
        called["count"] += 1
        return {"failed": False}

    orch = AutoResearchOrchestrator(
        cfg={
            "mode": "paper",
            "triggers": {
                "research_schedule_hours": 0.1,
                "min_paper_trades_before_research": 1,
                "cooldown_hours": 2,
            },
            "llm": {"enabled": False, "run_after_deterministic": False},
        },
        status_file=str(status),
        engine_state_file=str(engine),
        state_file=str(state),
        deterministic_runner=deterministic_runner,
        llm_runner=None,
        now_fn=lambda: 1000 + 600,
    )

    report = orch.run_once()
    assert report["triggered"] is False
    assert report["cooldown_blocked"] is True
    assert called["count"] == 0


def test_orchestrator_does_not_auto_live_deploy(tmp_path):
    status = tmp_path / "status.json"
    engine = tmp_path / "engine_state.json"
    state = tmp_path / "auto_state.json"
    _write_json(status, {"current_regime": {"BTCUSDT": "RANGE"}, "risk_caps_status": {"daily_pnl": 0}})
    _write_json(engine, {"paper_trade_history": [{}] * 10, "strategy_performance_history": []})

    orch = AutoResearchOrchestrator(
        cfg={
            "mode": "paper",
            "triggers": {
                "research_schedule_hours": 1,
                "min_paper_trades_before_research": 1,
                "cooldown_hours": 0,
            },
            "llm": {"enabled": False, "run_after_deterministic": False},
        },
        status_file=str(status),
        engine_state_file=str(engine),
        state_file=str(state),
        deterministic_runner=lambda *_: {"failed": False, "next_state": "ready_for_review"},
        llm_runner=None,
        now_fn=lambda: 4000,
    )

    report = orch.run_once()
    assert report["triggered"] is True
    assert report["deterministic"].get("next_state") != "approved_for_live_full"
    assert report["deterministic"].get("next_state") != "live_full_active"
