import asyncio
from unittest.mock import patch

from packages.core.master_engine import MasterEngine
from packages.core.models import DecisionRecord, MarketSnapshot
from packages.execution.adapters import PaperExecutionAdapter


REQUIRED_FIELDS = {
    "regime",
    "eligible_strategies",
    "score_breakdown",
    "selected_candidate",
    "side",
    "qty",
    "blocked_reason",
    "caps_status",
}


def _cfg(tmp_path):
    return {
        "mode": "paper",
        "symbols": ["BTCUSDT"],
        "engine": {
            "stale_after_sec": 60,
            "profile_update_sec": 60,
            "decision_interval_sec": 1,
        },
        "risk": {
            "max_daily_loss": 100,
            "max_total_exposure_notional": 1_000_000,
            "max_leverage": 5,
            "max_open_positions": 5,
            "per_symbol_exposure_cap": {},
        },
        "selector": {"base_edge": {"TrendCore": 0.1}},
        "telemetry": {
            "audit_db": str(tmp_path / "audit.db"),
            "status_file": str(tmp_path / "status.json"),
        },
        "account": {"equity": 1000},
        "sizing": {"base_qty": 1.0},
        "strategy_profiles": {},
        "strategy_configs": {"TrendCore": {"default": {}}},
    }


def _decision():
    return DecisionRecord(
        symbol="BTCUSDT",
        regime="TREND_UP",
        eligible_strategies=["TrendCore:default"],
        score_breakdown={"TrendCore:default": 0.9},
        selected_candidate="TrendCore:default",
        selected_strategy="TrendCore",
        selected_config="default",
        sizing={"confidence": 0.8},
    )


def test_order_submitted_includes_full_explanation(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.data.market["BTCUSDT"] = MarketSnapshot(symbol="BTCUSDT", price=100, bid=99, ask=101)
    events = []
    with patch("packages.core.master_engine.log_event", side_effect=lambda evt, payload: events.append((evt, payload))):
        asyncio.run(engine._execute_decision(_decision()))

    payload = [p for evt, p in events if evt == "order_submitted"][0]
    assert REQUIRED_FIELDS.issubset(payload.keys())
    assert payload["blocked_reason"] is None


def test_decision_blocked_includes_full_explanation(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.data.market["BTCUSDT"] = MarketSnapshot(symbol="BTCUSDT", price=100, bid=99, ask=101)
    engine.risk.trigger_safe_pause()
    events = []
    with patch("packages.core.master_engine.log_event", side_effect=lambda evt, payload: events.append((evt, payload))):
        asyncio.run(engine._execute_decision(_decision()))

    payload = [p for evt, p in events if evt == "decision_blocked"][0]
    assert REQUIRED_FIELDS.issubset(payload.keys())
    assert payload["blocked_reason"] == "safe_pause"


def test_decision_blocked_when_confidence_missing(tmp_path):
    engine = MasterEngine(_cfg(tmp_path), PaperExecutionAdapter())
    engine.data.market["BTCUSDT"] = MarketSnapshot(symbol="BTCUSDT", price=100, bid=99, ask=101)
    decision = _decision()
    decision.sizing = {}
    events = []
    with patch("packages.core.master_engine.log_event", side_effect=lambda evt, payload: events.append((evt, payload))):
        asyncio.run(engine._execute_decision(decision))

    payload = [p for evt, p in events if evt == "decision_blocked"][0]
    assert payload["blocked_reason"] == "invalid_sizing_confidence"
