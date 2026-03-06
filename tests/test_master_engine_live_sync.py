import asyncio

from packages.core.master_engine import MasterEngine
from packages.core.models import DecisionRecord, MarketSnapshot
from packages.execution.adapters import PaperExecutionAdapter


def _cfg(audit_db: str, mode: str) -> dict:
    return {
        "mode": mode,
        "symbols": ["BTCUSDT"],
        "engine": {
            "stale_after_sec": 30,
            "profile_update_sec": 60,
            "decision_interval_sec": 1,
            "account_stale_after_sec": 10,
        },
        "risk": {
            "max_daily_loss": 1000,
            "max_total_exposure_notional": 1_000_000,
            "max_leverage": 50,
            "max_open_positions": 5,
            "per_symbol_exposure_cap": {},
        },
        "selector": {"base_edge": {}},
        "account": {"equity": 10_000},
        "telemetry": {"audit_db": audit_db, "status_file": "runtime/status.json"},
        "sizing": {"base_qty": 0.01},
        "strategy_profiles": {},
        "strategy_configs": {"TrendCore": {}, "RangeMR": {}},
    }


def test_live_mode_does_not_apply_local_paper_fill(tmp_path):
    execution = PaperExecutionAdapter()
    engine = MasterEngine(_cfg(str(tmp_path / "audit.db"), mode="live"), execution)
    engine.data.market["BTCUSDT"] = MarketSnapshot(symbol="BTCUSDT", price=100, bid=99, ask=101)

    decision = DecisionRecord(
        symbol="BTCUSDT",
        regime="RANGE",
        eligible_strategies=["RangeMR:default"],
        score_breakdown={"RangeMR:default": 1.0},
        selected_strategy="RangeMR",
        selected_config="default",
        selected_side="BUY",
        sizing={"confidence": 1.0},
    )

    asyncio.run(engine._execute_decision(decision))

    assert "BTCUSDT" not in engine.data.account_state["positions"]
