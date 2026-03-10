from __future__ import annotations

from packages.backtest.engine import CandleBacktester
from packages.core.models import MarketSnapshot, Regime, StrategyContext


def test_filter_gates_accept_and_reject() -> None:
    bt = CandleBacktester()
    good = MarketSnapshot(
        symbol="BTCUSDT",
        price=101.0,
        bid=101.0,
        ask=101.0,
        candle_close=100.0,
        atr=1.0,
        rsi=60.0,
        trend_slope=0.002,
        session_bucket="london",
        range_compression_score=0.4,
        breakout_distance_from_recent_range=0.1,
        rsi_1h=58.0,
        rsi_4h=55.0,
        ts=10.0,
    )
    bad = MarketSnapshot(
        symbol="BTCUSDT",
        price=101.0,
        bid=101.0,
        ask=101.0,
        candle_close=100.0,
        atr=1.0,
        rsi=60.0,
        trend_slope=-0.002,
        session_bucket="asia",
        range_compression_score=0.02,
        breakout_distance_from_recent_range=1.3,
        rsi_1h=45.0,
        rsi_4h=44.0,
        ts=10.0,
    )
    cfg = {
        "composition": {
            "entry_family": "TrendPullback",
            "filter_pack": "none",
            "filter_modules": [
                "trend_slope_gate",
                "session_gate",
                "compression_gate",
                "range_quality_gate",
                "htf_alignment_gate",
            ],
            "exit_pack": "passthrough",
        }
    }
    assert bt.signal_for_snapshot("TrendPullback", good, Regime.TREND_UP, cfg) == 1
    assert bt.signal_for_snapshot("TrendPullback", bad, Regime.TREND_UP, cfg) == 0


def test_fixed_rr_exit_pack_sets_take_profit() -> None:
    bt = CandleBacktester()
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=101.0, bid=101.0, ask=101.0, candle_close=100.0, atr=1.0, rsi=60.0, ts=1.0)
    cfg = {
        "atr_stop_mult": 2.0,
        "composition": {"entry_family": "TrendCore", "filter_pack": "safe", "exit_pack": "fixed_rr"},
        "exits": {"fixed_rr": {"rr": 2.0}},
    }
    signal = bt.strategy_evaluator.evaluate("TrendCore", StrategyContext(snapshot=snapshot, regime=Regime.TREND_UP, config=cfg))
    assert signal is not None
    assert signal.stop_price is not None
    risk = snapshot.price - signal.stop_price
    assert signal.take_profit == snapshot.price + (risk * 2.0)


def test_atr_trail_and_time_decay_exit_metadata() -> None:
    bt = CandleBacktester()
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=101.0, bid=101.0, ask=101.0, candle_close=100.0, atr=1.0, rsi=60.0, ts=1.0)
    atr_cfg = {
        "atr_stop_mult": 2.0,
        "composition": {"entry_family": "TrendCore", "filter_pack": "safe", "exit_pack": "atr_trail"},
        "exits": {"atr_trail": {"trail_mult": 1.8}},
    }
    time_cfg = {
        "atr_stop_mult": 2.0,
        "composition": {"entry_family": "TrendCore", "filter_pack": "safe", "exit_pack": "time_decay_exit"},
        "exits": {"time_decay_exit": {"max_bars": 3}},
    }
    atr_signal = bt.strategy_evaluator.evaluate("TrendCore", StrategyContext(snapshot=snapshot, regime=Regime.TREND_UP, config=atr_cfg))
    time_signal = bt.strategy_evaluator.evaluate("TrendCore", StrategyContext(snapshot=snapshot, regime=Regime.TREND_UP, config=time_cfg))
    assert atr_signal is not None and atr_signal.meta.get("trail_mult") == 1.8
    assert time_signal is not None and time_signal.meta.get("time_stop_bars") == 3


def test_partial_tp_runner_metadata_and_backtest_time_exit() -> None:
    bt = CandleBacktester()
    snapshot = MarketSnapshot(symbol="BTCUSDT", price=101.0, bid=101.0, ask=101.0, candle_close=100.0, atr=1.0, rsi=60.0, ts=1.0)
    partial_cfg = {
        "atr_stop_mult": 2.0,
        "composition": {"entry_family": "TrendCore", "filter_pack": "safe", "exit_pack": "partial_tp_runner"},
        "exits": {"partial_tp_runner": {"partial_rr": 1.0, "partial_fraction": 0.5, "runner_trail_mult": 1.1}},
    }
    signal = bt.strategy_evaluator.evaluate("TrendCore", StrategyContext(snapshot=snapshot, regime=Regime.TREND_UP, config=partial_cfg))
    assert signal is not None
    assert signal.meta.get("partial_take_profit") is not None
    assert signal.meta.get("partial_fraction") == 0.5

    time_signal = bt.strategy_evaluator.evaluate(
        "TrendCore",
        StrategyContext(
            snapshot=snapshot,
            regime=Regime.TREND_UP,
            config={
                "atr_stop_mult": 2.0,
                "composition": {"entry_family": "TrendCore", "filter_pack": "safe", "exit_pack": "time_decay_exit"},
                "exits": {"time_decay_exit": {"max_bars": 2}},
            },
        ),
    )
    assert time_signal is not None and time_signal.meta.get("time_stop_bars") == 2


def test_existing_and_new_family_support_filter_plus_exit_pack() -> None:
    bt = CandleBacktester()
    snap = MarketSnapshot(
        symbol="BTCUSDT",
        price=101.0,
        bid=101.0,
        ask=101.0,
        candle_close=100.0,
        atr=1.2,
        rsi=58.0,
        trend_slope=0.002,
        session_bucket="new_york",
        range_compression_score=0.3,
        breakout_distance_from_recent_range=0.2,
        rsi_1h=57.0,
        rsi_4h=56.0,
        ts=7.0,
    )
    trend_cfg = {
        "atr_stop_mult": 2.0,
        "composition": {
            "entry_family": "TrendCore",
            "filter_pack": "none",
            "filter_modules": ["trend_slope_gate", "htf_alignment_gate"],
            "exit_pack": "fixed_rr",
        },
    }
    new_family_cfg = {
        "composition": {
            "entry_family": "TrendPullback",
            "filter_pack": "none",
            "filter_modules": ["trend_slope_gate", "session_gate"],
            "exit_pack": "atr_trail",
        }
    }
    assert bt.signal_for_snapshot("TrendCore", snap, Regime.TREND_UP, trend_cfg) == 1
    assert bt.signal_for_snapshot("TrendPullback", snap, Regime.TREND_UP, new_family_cfg) == 1
