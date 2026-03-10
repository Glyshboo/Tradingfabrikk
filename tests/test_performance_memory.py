from packages.selector.performance_memory import PerformanceMemory


def test_memory_update_and_score_components_positive_pnl():
    mem = PerformanceMemory({"pnl_scale": 0.1, "max_adjustment": 0.1})
    mem.update("BTCUSDT", "TREND_UP", "TrendCore", "default", pnl=0.2, source="paper", ts=1000)

    comp = mem.score_components("BTCUSDT", "TREND_UP", "TrendCore", "default", ts=1000)

    assert comp["memory_sample_count"] > 0
    assert comp["learned_adjustment"] > 0
    assert comp["uncertainty_penalty"] > 0


def test_memory_decay_reduces_sample_weight_over_time():
    mem = PerformanceMemory({"decay_half_life_sec": 10, "pnl_scale": 0.1, "max_adjustment": 0.1})
    mem.update("BTCUSDT", "RANGE", "RangeMR", "c1", pnl=0.15, source="paper", ts=100)
    fresh = mem.score_components("BTCUSDT", "RANGE", "RangeMR", "c1", ts=100)
    decayed = mem.score_components("BTCUSDT", "RANGE", "RangeMR", "c1", ts=140)

    assert decayed["memory_sample_count"] < fresh["memory_sample_count"]
    assert decayed["learned_adjustment"] < fresh["learned_adjustment"]


def test_challenger_updates_relative_component():
    mem = PerformanceMemory({"pnl_scale": 0.1})
    mem.update("ETHUSDT", "RANGE", "RangeMR", "c2", pnl=0.05, source="challenger", challenger_relative=0.8, ts=50)

    comp = mem.score_components("ETHUSDT", "RANGE", "RangeMR", "c2", ts=50)

    assert comp["memory_challenger_relative"] > 0


def test_cold_start_has_small_uncertainty_penalty_without_samples():
    mem = PerformanceMemory({"cold_start_uncertainty_penalty": 0.009})

    comp = mem.score_components("BTCUSDT", "TREND_UP", "TrendPullback", "c1", ts=10)

    assert comp["memory_sample_count"] == 0.0
    assert comp["learned_adjustment"] == 0.0
    assert comp["uncertainty_penalty"] == 0.009
