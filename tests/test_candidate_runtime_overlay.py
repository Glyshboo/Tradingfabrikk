from __future__ import annotations

import asyncio
import time

from packages.core.master_engine import MasterEngine
from packages.core.models import DecisionRecord
from packages.execution.adapters import PaperExecutionAdapter


def _cfg(tmp_path):
    return {
        "mode": "paper",
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
        "paper_candidate": {"window_sec": 1, "min_trades": 1},
    }


def test_candidate_overlay_resolution_and_micro_live_execution(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.candidate_registry.register(
        "cand_a",
        1.0,
        {
            "symbols": ["BTCUSDT"],
            "config_patch": {"strategy_configs": {"RangeMR": {"cand_cfg": {"rsi_low": 20, "rsi_high": 80, "base_confidence": 0.8}}}},
            "strategy_profile_patch": {"BTCUSDT": {"RANGE": [["RangeMR", "cand_cfg"]]}},
        },
    )
    engine.candidate_registry.transition("cand_a", "approved_for_micro_live")
    engine._sync_candidate_state_machine()

    overlay = engine.overlay_mgr.resolve("BTCUSDT", "RANGE")
    assert overlay.runtime_model == "challenger:micro_live"
    assert overlay.candidate_id == "cand_a"
    assert overlay.strategy_profiles["BTCUSDT"]["RANGE"] == [["RangeMR", "cand_cfg"]]

    decision = DecisionRecord(
        symbol="BTCUSDT",
        regime="RANGE",
        eligible_strategies=["RangeMR:cand_cfg"],
        score_breakdown={"RangeMR:cand_cfg": 1.0},
        selected_strategy="RangeMR",
        selected_config="cand_cfg",
        selected_side="BUY",
        sizing={"confidence": 1.0},
        runtime_model="challenger:micro_live",
        overlay_candidate_id="cand_a",
    )
    asyncio.run(engine._execute_decision(decision))
    assert engine.paper_trade_history[-1]["overlay_candidate_id"] == "cand_a"
    assert engine.paper_trade_history[-1]["runtime_model"] == "challenger:micro_live"
    assert engine.paper_trade_history[-1]["qty"] == 0.003


def test_paper_candidate_state_progression(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.candidate_registry.register("cand_p", 1.0, {"symbols": ["BTCUSDT"]})
    engine.candidate_registry.transition("cand_p", "paper_candidate_active")
    now = time.time()
    engine.paper_trade_history.append({"ts": now - 0.2, "overlay_candidate_id": "cand_p", "symbol": "BTCUSDT", "qty": 0.01})
    engine.active_paper_candidates = {"cand_p": {"state": "paper_candidate_active", "started_ts": now - 5, "symbols": ["BTCUSDT"]}}
    engine._evaluate_paper_candidates()
    assert engine.candidate_registry.get("cand_p")["state"] in {"paper_candidate_pass", "paper_candidate_fail"}
