from __future__ import annotations

import sys

import yaml

from apps import auto_research_runner
from apps import research_runner
from packages.core.master_engine import MasterEngine
from packages.execution.adapters import PaperExecutionAdapter


class _FakeRefreshService:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.schedule_calls = 0

    def refresh_exports(self, *, trigger: str, context: dict | None = None, force: bool = False):
        self.calls.append((trigger, context or {}))
        return {"refreshed": True, "trigger": trigger}

    def maybe_refresh_on_schedule(self, *, context: dict | None = None):
        self.schedule_calls += 1
        return {"refreshed": False, "skipped": "schedule_interval"}


def _active_cfg(tmp_path):
    return {
        "mode": "paper",
        "symbols": ["BTCUSDT"],
        "engine": {"stale_after_sec": 30, "profile_update_sec": 60, "decision_interval_sec": 1, "recovery_wait_sec": 0},
        "risk": {
            "max_daily_loss": 1000,
            "max_weekly_loss": 2000,
            "max_drawdown_pct": 0.2,
            "max_total_exposure_notional": 1_000_000,
            "max_leverage": 50,
            "max_open_positions": 5,
            "per_symbol_exposure_cap": {},
            "correlation_clusters": {},
        },
        "selector": {"base_edge": {"TrendCore": 0.1, "RangeMR": 0.1}},
        "account": {"equity": 10_000},
        "telemetry": {"audit_db": str(tmp_path / "audit.db"), "status_file": str(tmp_path / "status.json")},
        "sizing": {"base_qty": 0.01},
        "strategy_profiles": {"BTCUSDT": {"RANGE": [["RangeMR", "rmr_safe"]], "TREND_UP": [["TrendCore", "tc_safe"]]}},
        "strategy_configs": {
            "TrendCore": {"tc_safe": {"atr_stop_mult": 2, "time_stop_bars": 12, "base_confidence": 0.58}},
            "RangeMR": {"rmr_safe": {"rsi_low": 35, "rsi_high": 65, "base_confidence": 0.52}},
        },
        "state": {"engine_state_file": str(tmp_path / "engine_state.json"), "data_state_file": str(tmp_path / "data_state.json")},
        "review": {"queue_file": str(tmp_path / "review_queue.json"), "candidate_registry_file": str(tmp_path / "registry.json")},
    }


def test_refresh_triggered_after_research(monkeypatch, tmp_path):
    cfg_path = tmp_path / "active.yaml"
    space_path = tmp_path / "space.yaml"
    cfg = _active_cfg(tmp_path)
    cfg["exports"] = {"enabled": True}
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    space_path.write_text(yaml.safe_dump({"symbols": ["BTCUSDT"], "regimes": ["RANGE"], "strategy_families": ["RangeMR"]}), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(research_runner.ResearchOptimizer, "random_search", lambda *args, **kwargs: {
        "BTCUSDT|RANGE": [
            {
                "id": "cand_1",
                "score": 1.0,
                "symbol": "BTCUSDT",
                "regime": "RANGE",
                "strategy_family": "RangeMR",
                "strategy_config_patch": {},
                "walk_forward": {"out_sample": {"pnl": 1.0}},
                "plausible": True,
                "rejection_reasons": [],
                "evaluation": {},
            }
        ]
    })

    fake = _FakeRefreshService()
    monkeypatch.setattr(research_runner.ExportRefreshService, "from_config", lambda *_: fake)
    report = research_runner.run_research(config_path=str(cfg_path), space_path=str(space_path), samples=1)

    assert report["export_refresh"]["refreshed"] is True
    assert any(trigger == "research_runner" for trigger, _ in fake.calls)


def test_refresh_triggered_after_candidate_state_change(tmp_path):
    fake = _FakeRefreshService()
    engine = MasterEngine(_active_cfg(tmp_path), PaperExecutionAdapter(), export_refresh_service=fake)
    engine.candidate_registry.register("cand_state", 1.0, {"symbols": ["BTCUSDT"]})
    engine.candidate_registry.transition("cand_state", "paper_candidate_active")

    engine._sync_candidate_state_machine()

    assert any(trigger == "candidate_change" for trigger, _ in fake.calls)


def test_auto_research_runner_triggers_refresh(monkeypatch, tmp_path):
    cfg_path = tmp_path / "active.yaml"
    cfg = _active_cfg(tmp_path)
    cfg["auto_research"] = {"artifact_file": str(tmp_path / "auto_report.json"), "triggers": {}, "llm": {"enabled": False}}
    cfg["exports"] = {"enabled": True}
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    fake = _FakeRefreshService()
    monkeypatch.setattr(auto_research_runner.ExportRefreshService, "from_config", lambda *_: fake)

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            pass

        def run_once(self):
            return {"triggered": True, "reasons": ["schedule"]}

    monkeypatch.setattr(auto_research_runner, "AutoResearchOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(sys, "argv", ["auto_research_runner", "--config", str(cfg_path)])

    auto_research_runner.main()
    assert any(trigger == "auto_research_runner" for trigger, _ in fake.calls)
