from __future__ import annotations

from packages.core.master_engine import MasterEngine
from packages.execution.adapters import PaperExecutionAdapter


def _cfg(tmp_path):
    return {
        "mode": "paper",
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "engine": {"stale_after_sec": 60, "profile_update_sec": 999, "decision_interval_sec": 1, "recovery_wait_sec": 0},
        "account": {"equity": 10000},
        "selector": {"base_edge": {"TrendCore": 0.1, "RangeMR": 0.1}},
        "strategy_profiles": {"BTCUSDT": {"RANGE": [["RangeMR", "rmr_safe"]]}, "ETHUSDT": {"RANGE": [["RangeMR", "rmr_safe"]]}},
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
        "micro_live": {"enabled": True, "risk_multiplier": 0.3, "max_total_exposure_notional": 10, "max_symbols": 1},
    }


def test_micro_live_one_symbol_guard(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.active_micro_live = {
        "c1": {"symbols": ["BTCUSDT"], "state": "micro_live_active"},
        "c2": {"symbols": ["ETHUSDT"], "state": "micro_live_active"},
    }
    context = engine._micro_live_context_for_symbol("BTCUSDT")
    assert context is not None
    assert context["blocked"] is True
    assert context["reason"] == "micro_live_one_symbol_only"
