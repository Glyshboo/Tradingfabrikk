from __future__ import annotations

from packages.core.models import StrategyContext, StrategySignal
from packages.strategies.base import FilterModule


class ConfigurableFilterModule(FilterModule):
    key: str

    def _cfg(self, context: StrategyContext) -> dict:
        cfg = context.config.get("filters", {}) if isinstance(context.config, dict) else {}
        row = cfg.get(self.key, {}) if isinstance(cfg, dict) else {}
        return row if isinstance(row, dict) else {}

    def _enabled(self, context: StrategyContext) -> bool:
        return bool(self._cfg(context).get("enabled", True))


class TrendSlopeGate(ConfigurableFilterModule):
    name = "trend_slope_gate"
    key = name

    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        if not self._enabled(context):
            return True
        slope = context.snapshot.trend_slope
        if slope is None:
            return False
        min_abs = float(self._cfg(context).get("min_abs_slope", 0.0001))
        if signal.side == "BUY":
            return slope >= min_abs
        if signal.side == "SELL":
            return slope <= -min_abs
        return False


class SessionGate(ConfigurableFilterModule):
    name = "session_gate"
    key = name

    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        if not self._enabled(context):
            return True
        session = context.snapshot.session_bucket
        if not session:
            return False
        allowed = self._cfg(context).get("allowed_sessions", ["london", "new_york", "overlap"])
        normalized = {str(s).lower() for s in allowed if isinstance(s, str)}
        return session.lower() in normalized


class CompressionGate(ConfigurableFilterModule):
    name = "compression_gate"
    key = name

    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        if not self._enabled(context):
            return True
        score = context.snapshot.range_compression_score
        if score is None:
            return False
        cfg = self._cfg(context)
        min_score = float(cfg.get("min_score", 0.15))
        max_score = float(cfg.get("max_score", 1.0))
        return min_score <= score <= max_score


class RangeQualityGate(ConfigurableFilterModule):
    name = "range_quality_gate"
    key = name

    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        if not self._enabled(context):
            return True
        distance = context.snapshot.breakout_distance_from_recent_range
        if distance is None:
            return False
        max_abs_distance = float(self._cfg(context).get("max_abs_distance", 0.75))
        return abs(distance) <= max_abs_distance


class HTFAlignmentGate(ConfigurableFilterModule):
    name = "htf_alignment_gate"
    key = name

    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        if not self._enabled(context):
            return True
        rsi_1h = context.snapshot.rsi_1h
        rsi_4h = context.snapshot.rsi_4h
        if rsi_1h is None or rsi_4h is None:
            return False
        upper = float(self._cfg(context).get("bullish_threshold", 50.0))
        lower = float(self._cfg(context).get("bearish_threshold", 50.0))
        if signal.side == "BUY":
            return rsi_1h >= upper and rsi_4h >= upper
        if signal.side == "SELL":
            return rsi_1h <= lower and rsi_4h <= lower
        return False
