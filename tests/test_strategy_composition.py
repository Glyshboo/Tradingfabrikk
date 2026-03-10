from __future__ import annotations

from packages.backtest.engine import CandleBacktester
from packages.core.master_engine import MasterEngine
from packages.core.models import MarketSnapshot, Regime, StrategyContext
from packages.execution.adapters import PaperExecutionAdapter
from packages.strategies.range_mr import RangeMR
from packages.strategies.trend_core import TrendCore


def _engine_cfg() -> dict:
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
        "telemetry": {"audit_db": "runtime/test_audit.db", "status_file": "runtime/status.json"},
        "sizing": {"base_qty": 0.01},
        "strategy_profiles": {"BTCUSDT": {}},
        "strategy_configs": {"TrendCore": {}, "RangeMR": {}},
    }


def test_composition_supports_filter_and_exit_packs_fail_closed() -> None:
    backtester = CandleBacktester()
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=101.0, bid=101.0, ask=101.0, candle_close=100.0, atr=1.2, rsi=55.0, ts=1.0)

    valid_cfg = {
        "atr_stop_mult": 2.0,
        "composition": {
            "entry_family": "TrendCore",
            "filter_pack": "safe",
            "filter_modules": ["signal_sanity"],
            "exit_pack": "protective",
        },
    }
    invalid_cfg = {
        "atr_stop_mult": 2.0,
        "composition": {
            "entry_family": "TrendCore",
            "filter_pack": "safe",
            "filter_modules": ["unknown_filter"],
            "exit_pack": "protective",
        },
    }

    assert backtester.signal_for_snapshot("TrendCore", snapshot, Regime.TREND_UP, valid_cfg) == 1
    assert backtester.signal_for_snapshot("TrendCore", snapshot, Regime.TREND_UP, invalid_cfg) == 0


def test_default_composition_keeps_legacy_trendcore_and_rangemr_behavior() -> None:
    backtester = CandleBacktester()
    trend = TrendCore()
    range_mr = RangeMR()

    trend_snapshot = MarketSnapshot(symbol="BTCUSDT", price=101.0, bid=101.0, ask=101.0, candle_close=100.0, atr=1.4, rsi=60.0, ts=1.0)
    range_snapshot = MarketSnapshot(symbol="ETHUSDT", price=100.0, bid=100.0, ask=100.0, candle_close=100.0, atr=1.1, rsi=70.0, ts=2.0)

    trend_cfg = {"atr_stop_mult": 2.0, "base_confidence": 0.55}
    range_cfg = {"rsi_low": 35, "rsi_high": 65, "base_confidence": 0.52}

    trend_legacy = trend.generate_for_context(StrategyContext(snapshot=trend_snapshot, regime=Regime.TREND_UP, config=trend_cfg))
    range_legacy = range_mr.generate_for_context(StrategyContext(snapshot=range_snapshot, regime=Regime.RANGE, config=range_cfg))

    assert backtester.signal_for_snapshot("TrendCore", trend_snapshot, Regime.TREND_UP, trend_cfg) == (1 if trend_legacy else 0)
    assert backtester.signal_for_snapshot("RangeMR", range_snapshot, Regime.RANGE, range_cfg) == (-1 if range_legacy else 0)


def test_runtime_and_backtest_share_same_strategy_evaluator_truth() -> None:
    engine = MasterEngine(_engine_cfg(), PaperExecutionAdapter())
    backtester = CandleBacktester()
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=99.0, bid=99.0, ask=99.0, candle_close=100.0, atr=1.3, rsi=45.0, ts=3.0)
    config = {"atr_stop_mult": 2.0, "base_confidence": 0.55}

    runtime_signal = engine.strategy_evaluator.evaluate(
        "TrendCore", StrategyContext(snapshot=snapshot, regime=Regime.TREND_DOWN, config=config)
    )
    backtest_position = backtester.signal_for_snapshot("TrendCore", snapshot, Regime.TREND_DOWN, config)

    runtime_position = 1 if runtime_signal and runtime_signal.side == "BUY" else -1 if runtime_signal and runtime_signal.side == "SELL" else 0
    assert runtime_position == backtest_position
