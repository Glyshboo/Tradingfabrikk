from packages.core.master_engine import MasterEngine
from packages.core.models import MarketSnapshot
from packages.execution.adapters import PaperExecutionAdapter


def _cfg(tmp_path):
    return {
        "mode": "paper",
        "symbols": ["BTCUSDT"],
        "engine": {"stale_after_sec": 30, "profile_update_sec": 60, "decision_interval_sec": 1},
        "risk": {
            "max_daily_loss": 1000,
            "max_total_exposure_notional": 1_000_000,
            "max_leverage": 50,
            "max_open_positions": 5,
            "per_symbol_exposure_cap": {},
            "correlation_clusters": {},
            "correlation_direction_cap": 2,
        },
        "selector": {
            "base_edge": {},
            "performance_memory": {"paper_window_sec": 1, "pnl_scale": 0.1},
        },
        "account": {"equity": 10_000},
        "telemetry": {"audit_db": str(tmp_path / "audit.db"), "status_file": str(tmp_path / "status.json")},
        "sizing": {"base_qty": 0.01},
        "strategy_profiles": {},
        "strategy_configs": {"TrendCore": {}, "RangeMR": {}},
        "state": {"engine_state_file": str(tmp_path / "engine_state.json"), "data_state_file": str(tmp_path / "data_state.json")},
    }


def test_engine_updates_memory_from_paper_and_challenger(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.data.market["BTCUSDT"] = MarketSnapshot(symbol="BTCUSDT", price=110, bid=109, ask=111, ts=1000)

    engine.paper_trade_history = [
        {
            "symbol": "BTCUSDT",
            "regime": "TREND_UP",
            "strategy": "TrendCore",
            "config": "default",
            "side": "BUY",
            "qty": 1.0,
            "entry_basis": 100.0,
            "opened_ts": 900,
            "window_sec": 50,
            "status": "pending",
        }
    ]
    engine._evaluate_paper_trade_outcomes()

    engine.challenger_eval_history = [
        {
            "symbol": "BTCUSDT",
            "regime": "TREND_UP",
            "strategy": "TrendCore",
            "config": "default",
            "side": "BUY",
            "signal_ts": 800,
            "window_sec": 100,
            "hypothetical_qty": 1.0,
            "entry_basis": 100.0,
            "status": "pending",
        }
    ]
    engine._evaluate_challenger_signals()

    comp = engine.performance_memory.score_components("BTCUSDT", "TREND_UP", "TrendCore", "default")
    assert comp["memory_sample_count"] > 1


def test_engine_persists_performance_memory_state(tmp_path):
    cfg = _cfg(tmp_path)
    engine = MasterEngine(cfg, PaperExecutionAdapter())
    engine.performance_memory.update("BTCUSDT", "RANGE", "RangeMR", "c1", pnl=0.1, source="paper", ts=100)
    engine._persist_state()

    reloaded = MasterEngine(cfg, PaperExecutionAdapter())
    comp = reloaded.performance_memory.score_components("BTCUSDT", "RANGE", "RangeMR", "c1", ts=100)
    assert comp["memory_sample_count"] > 0
