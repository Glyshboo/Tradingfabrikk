import asyncio

from packages.core.master_engine import MasterEngine
from packages.core.models import DecisionRecord
from packages.execution.adapters import PaperExecutionAdapter


def _cfg(audit_db: str) -> dict:
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
        "selector": {"base_edge": {}},
        "account": {"equity": 10_000},
        "telemetry": {"audit_db": audit_db, "status_file": "runtime/status.json"},
        "sizing": {"base_qty": 0.01},
        "strategy_profiles": {},
        "strategy_configs": {"TrendCore": {}, "RangeMR": {}},
    }


def test_execute_decision_uses_selected_side_for_order(tmp_path):
    execution = PaperExecutionAdapter()
    engine = MasterEngine(_cfg(str(tmp_path / "audit.db")), execution)
    decision = DecisionRecord(
        symbol="BTCUSDT",
        regime="RANGE",
        eligible_strategies=["RangeMR:default"],
        score_breakdown={"RangeMR:default": 1.0},
        selected_strategy="RangeMR",
        selected_config="default",
        selected_side="SELL",
        sizing={"confidence": 0.95},
    )

    asyncio.run(engine._execute_decision(decision))

    assert len(execution.orders) == 1
    assert execution.orders[0]["side"] == "SELL"
