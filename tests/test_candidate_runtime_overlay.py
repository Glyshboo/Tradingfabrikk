from __future__ import annotations

import time

from packages.core.master_engine import MasterEngine
from packages.execution.adapters import PaperExecutionAdapter


def _cfg(tmp_path, mode: str = "paper"):
    return {
        "mode": mode,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "engine": {"stale_after_sec": 60, "profile_update_sec": 999, "decision_interval_sec": 1, "recovery_wait_sec": 0},
        "account": {"equity": 10000},
        "selector": {"base_edge": {"TrendCore": 0.1, "RangeMR": 0.1}},
        "strategy_profiles": {
            "BTCUSDT": {"RANGE": [["RangeMR", "rmr_safe"]], "TREND_UP": [["TrendCore", "tc_safe"]]},
            "ETHUSDT": {"RANGE": [["RangeMR", "rmr_safe"]], "TREND_UP": [["TrendCore", "tc_safe"]]},
        },
        "strategy_configs": {
            "TrendCore": {"tc_safe": {"atr_stop_mult": 2, "time_stop_bars": 12, "base_confidence": 0.6}},
            "RangeMR": {"rmr_safe": {"rsi_low": 30, "rsi_high": 70, "base_confidence": 0.5}},
        },
        "sizing": {"base_qty": 0.01},
        "telemetry": {"audit_db": str(tmp_path / "audit.db"), "status_file": str(tmp_path / "status.json")},
        "state": {"engine_state_file": str(tmp_path / "engine_state.json"), "data_state_file": str(tmp_path / "data_state.json")},
        "review": {"queue_file": str(tmp_path / "review.json"), "candidate_registry_file": str(tmp_path / "registry.json")},
        "risk": {
            "max_daily_loss": 100,
            "max_weekly_loss": 500,
            "max_drawdown_pct": 0.2,
            "max_total_exposure_notional": 20000,
            "max_open_positions": 4,
            "max_leverage": 5,
            "per_symbol_exposure_cap": {"BTCUSDT": 12000, "ETHUSDT": 12000},
            "correlation_clusters": {},
        },
        "micro_live": {"enabled": True, "risk_multiplier": 0.3, "max_total_exposure_notional": 100000, "max_symbols": 1},
        "paper_candidate": {"window_sec": 1, "compare_window_sec": 1, "min_trades": 1},
        "incubation": {
            "strict_candidate_kinds": ["combination_candidate", "new_family_candidate"],
            "strict_revalidation_min_avg_pnl": 0.01,
            "strict_revalidation_min_evaluations": 2,
            "strict_challenger_hold_sec": 0,
        },
    }


def _register_paper_candidate(engine: MasterEngine, cid: str, confidence: float = 0.9) -> None:
    engine.candidate_registry.register(
        cid,
        1.0,
        {
            "symbols": ["BTCUSDT"],
            "config_patch": {"strategy_configs": {"RangeMR": {f"{cid}_cfg": {"rsi_low": 20, "rsi_high": 80, "base_confidence": confidence}}}},
            "strategy_profile_patch": {"BTCUSDT": {"RANGE": [["RangeMR", f"{cid}_cfg"]]}},
        },
    )
    engine.candidate_registry.transition(cid, "paper_candidate_active")


def test_paper_mode_baseline_champion_with_shadow_challenger(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    _register_paper_candidate(engine, "cand_a")
    engine._sync_candidate_state_machine()

    runtime = engine.overlay_mgr.resolve_runtime("BTCUSDT", "RANGE", "paper")
    assert runtime.champion.runtime_model == "baseline"
    assert runtime.champion.candidate_id is None
    assert [c.candidate_id for c in runtime.challengers] == ["cand_a"]


def test_backtest_pass_auto_progresses_to_paper_smoke_running(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.candidate_registry.register("cand_flow", 1.0, {"symbols": ["BTCUSDT"]})
    engine.candidate_registry.transition("cand_flow", "config_generated")
    engine.candidate_registry.transition("cand_flow", "backtest_pass")
    engine._auto_progress_paper_lifecycle()
    assert engine.candidate_registry.get("cand_flow")["state"] == "paper_smoke_running"


def test_multiple_challengers_same_symbol_in_paper(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    _register_paper_candidate(engine, "cand_a")
    _register_paper_candidate(engine, "cand_b")
    engine._sync_candidate_state_machine()

    runtime = engine.overlay_mgr.resolve_runtime("BTCUSDT", "RANGE", "paper")
    assert runtime.champion.runtime_model == "baseline"
    challenger_ids = sorted(c.candidate_id for c in runtime.challengers)
    assert challenger_ids == ["cand_a", "cand_b"]

    now = time.time()
    engine.challenger_eval_history = [
        {
            "symbol": "BTCUSDT",
            "regime": "RANGE",
            "strategy": "RangeMR",
            "config": "cand_a_cfg",
            "side": "BUY",
            "signal_ts": now - 2,
            "runtime_model": "challenger:paper_candidate",
            "overlay_candidate_id": "cand_a",
            "hypothetical_qty": 0.01,
            "entry_basis": 100.0,
            "window_sec": 1,
            "status": "evaluated",
            "result_pnl": 0.1,
            "result_ts": now - 0.1,
        },
        {
            "symbol": "BTCUSDT",
            "regime": "RANGE",
            "strategy": "RangeMR",
            "config": "cand_b_cfg",
            "side": "SELL",
            "signal_ts": now - 2,
            "runtime_model": "challenger:paper_candidate",
            "overlay_candidate_id": "cand_b",
            "hypothetical_qty": 0.01,
            "entry_basis": 100.0,
            "window_sec": 1,
            "status": "evaluated",
            "result_pnl": -0.1,
            "result_ts": now - 0.1,
        },
    ]
    engine.active_paper_candidates = {
        "cand_a": {"state": "paper_candidate_active", "started_ts": now - 5, "symbols": ["BTCUSDT"]},
        "cand_b": {"state": "paper_candidate_active", "started_ts": now - 5, "symbols": ["BTCUSDT"]},
    }
    engine._evaluate_paper_candidates()
    assert engine.candidate_registry.get("cand_a")["state"] == "paper_candidate_pass"
    assert engine.candidate_registry.get("cand_b")["state"] == "edge_decay"


def test_auto_progression_to_ready_for_review_from_paper_pass(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    _register_paper_candidate(engine, "cand_pass")
    now = time.time()
    engine.challenger_eval_history = [
        {
            "symbol": "BTCUSDT",
            "regime": "RANGE",
            "strategy": "RangeMR",
            "config": "cand_pass_cfg",
            "side": "BUY",
            "signal_ts": now - 2,
            "runtime_model": "challenger:paper_candidate",
            "overlay_candidate_id": "cand_pass",
            "hypothetical_qty": 0.01,
            "entry_basis": 100.0,
            "window_sec": 1,
            "status": "evaluated",
            "result_pnl": 0.2,
            "result_ts": now - 0.1,
        },
    ]
    engine.active_paper_candidates = {
        "cand_pass": {"state": "paper_candidate_active", "started_ts": now - 5, "symbols": ["BTCUSDT"]},
    }
    engine._evaluate_paper_candidates()
    assert engine.candidate_registry.get("cand_pass")["state"] == "paper_candidate_pass"
    engine._auto_progress_paper_lifecycle()
    assert engine.candidate_registry.get("cand_pass")["state"] == "ready_for_review"
    assert len(engine.review_queue.list_ready()) == 1


def test_edge_decay_degrades_to_needs_revalidation(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    _register_paper_candidate(engine, "cand_decay")
    now = time.time()
    engine.challenger_eval_history = [
        {
            "symbol": "BTCUSDT",
            "regime": "RANGE",
            "strategy": "RangeMR",
            "config": "cand_decay_cfg",
            "side": "SELL",
            "signal_ts": now - 2,
            "runtime_model": "challenger:paper_candidate",
            "overlay_candidate_id": "cand_decay",
            "hypothetical_qty": 0.01,
            "entry_basis": 100.0,
            "window_sec": 1,
            "status": "evaluated",
            "result_pnl": -0.2,
            "result_ts": now - 0.1,
        },
    ]
    engine.active_paper_candidates = {
        "cand_decay": {"state": "paper_candidate_active", "started_ts": now - 5, "symbols": ["BTCUSDT"]},
    }
    engine._evaluate_paper_candidates()
    assert engine.candidate_registry.get("cand_decay")["state"] == "edge_decay"
    engine._auto_progress_paper_lifecycle()
    assert engine.candidate_registry.get("cand_decay")["state"] == "needs_revalidation"


def test_live_mode_overlay_resolution_still_conservative(tmp_path):
    engine = MasterEngine(_cfg(tmp_path, mode="live"), PaperExecutionAdapter())
    engine.candidate_registry.register(
        "cand_micro",
        1.0,
        {
            "symbols": ["BTCUSDT"],
            "config_patch": {"strategy_configs": {"RangeMR": {"cand_cfg": {"rsi_low": 20, "rsi_high": 80, "base_confidence": 0.8}}}},
            "strategy_profile_patch": {"BTCUSDT": {"RANGE": [["RangeMR", "cand_cfg"]]}},
        },
    )
    engine.candidate_registry.transition("cand_micro", "approved_for_micro_live")
    engine._sync_candidate_state_machine()

    runtime = engine.overlay_mgr.resolve_runtime("BTCUSDT", "RANGE", "live")
    assert runtime.champion.runtime_model == "challenger:micro_live"
    assert runtime.champion.candidate_id == "cand_micro"
    assert runtime.challengers == []


def test_strict_candidate_requires_revalidation_before_review(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.candidate_registry.register("cand_strict", 1.0, {"symbols": ["BTCUSDT"], "candidate_kind": "new_family_candidate", "track": "strict"})
    engine.candidate_registry.transition("cand_strict", "paper_candidate_pass")
    engine._auto_progress_paper_lifecycle()
    assert engine.candidate_registry.get("cand_strict")["state"] == "needs_revalidation"

    engine.candidate_registry.update_meta("cand_strict", artifacts_patch={"paper_challenger_result": {"avg_pnl": 0.03, "evaluated": 2}})
    engine._auto_progress_paper_lifecycle()
    assert engine.candidate_registry.get("cand_strict")["state"] == "ready_for_review"
