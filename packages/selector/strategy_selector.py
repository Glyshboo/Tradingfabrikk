from __future__ import annotations

from typing import Dict, List, Tuple

from packages.profiles.symbol_profile import SymbolProfile

from packages.core.models import DecisionRecord, Regime, StrategySignal
from packages.selector.performance_memory import PerformanceMemory


class StrategySelector:
    def __init__(
        self,
        base_edge: Dict[str, float],
        performance_memory: PerformanceMemory | None = None,
        cold_start_bias: Dict[str, float] | None = None,
        cold_start_max_samples: float = 6.0,
    ):
        self.base_edge = base_edge
        self.performance_memory = performance_memory
        self.cold_start_bias = cold_start_bias or {}
        self.cold_start_max_samples = max(float(cold_start_max_samples), 1.0)

    def select(
        self,
        symbol: str,
        regime: Regime,
        candidates: List[Tuple[str, str, StrategySignal]],
        cost_proxy: Dict[str, float],
        exposure_penalty: float,
        symbol_profile: SymbolProfile | None = None,
        current_positions: Dict[str, float] | None = None,
    ) -> DecisionRecord | None:
        if not candidates:
            return None
        scores = {}
        components: Dict[str, Dict[str, float]] = {}
        for strategy_name, cfg_name, signal in candidates:
            static_base_edge = float(self.base_edge.get(strategy_name, 0.0))
            signal_confidence = float(signal.confidence)
            base = static_base_edge + signal_confidence
            spread_cost = cost_proxy.get("spread", 0.0)
            slippage_cost = cost_proxy.get("slippage", 0.0)
            funding_cost = cost_proxy.get("funding", 0.0)
            corr_penalty = 0.0
            if current_positions:
                same_direction_abs = sum(
                    abs(qty)
                    for qty in current_positions.values()
                    if qty != 0 and ((qty > 0 and signal.side == "BUY") or (qty < 0 and signal.side == "SELL"))
                )
                corr_penalty = min(0.08, same_direction_abs * 0.01)
            profile_penalty = 0.0
            if symbol_profile:
                profile_penalty = max(0.0, 1.0 - symbol_profile.liquidity_signature) * 0.02
                funding_cost = max(funding_cost, max(0.0, symbol_profile.funding_behavior) * 0.01)
            memory = {
                "learned_adjustment": 0.0,
                "uncertainty_penalty": 0.0,
                "memory_sample_count": 0.0,
                "memory_sample_weight": 0.0,
                "memory_recent_pnl": 0.0,
                "memory_hit_rate": 0.5,
                "memory_avg_result": 0.0,
                "memory_challenger_relative": 0.0,
            }
            if self.performance_memory:
                memory = self.performance_memory.score_components(symbol, regime.value, strategy_name, cfg_name)
            cold_start_component = 0.0
            if strategy_name in self.cold_start_bias:
                sample_count = float(memory.get("memory_sample_count", 0.0) or 0.0)
                cold_weight = max(0.0, 1.0 - (sample_count / self.cold_start_max_samples))
                cold_start_component = float(self.cold_start_bias.get(strategy_name, 0.0)) * cold_weight
            total = (
                base
                + memory["learned_adjustment"]
                + cold_start_component
                - memory["uncertainty_penalty"]
                - spread_cost
                - slippage_cost
                - funding_cost
                - exposure_penalty
                - corr_penalty
                - profile_penalty
            )
            key = f"{strategy_name}:{cfg_name}"
            scores[key] = round(total, 6)
            components[key] = {
                "static_base_edge": round(static_base_edge, 6),
                "signal_confidence": round(signal_confidence, 6),
                "base": round(base, 6),
                "learned_adjustment": memory["learned_adjustment"],
                "family_cold_start_adjustment": round(cold_start_component, 6),
                "uncertainty_penalty": memory["uncertainty_penalty"],
                "spread_cost": round(spread_cost, 6),
                "slippage_cost": round(slippage_cost, 6),
                "funding_cost": round(funding_cost, 6),
                "exposure_penalty": round(exposure_penalty, 6),
                "correlation_penalty": round(corr_penalty, 6),
                "profile_penalty": round(profile_penalty, 6),
                "memory_sample_count": memory["memory_sample_count"],
                "memory_sample_weight": memory["memory_sample_weight"],
                "memory_recent_pnl": memory["memory_recent_pnl"],
                "memory_hit_rate": memory["memory_hit_rate"],
                "memory_avg_result": memory["memory_avg_result"],
                "memory_challenger_relative": memory["memory_challenger_relative"],
                "total": round(total, 6),
            }

        selected_key = max(scores, key=scores.get)
        strategy_name, cfg_name = selected_key.split(":", 1)
        sig = [c[2] for c in candidates if c[0] == strategy_name and c[1] == cfg_name][0]
        return DecisionRecord(
            symbol=symbol,
            regime=regime.value,
            eligible_strategies=[f"{c[0]}:{c[1]}" for c in candidates],
            score_breakdown=scores,
            score_components=components,
            selected_candidate=selected_key,
            selected_strategy=strategy_name,
            selected_config=cfg_name,
            selected_side=sig.side,
            sizing={
                "confidence": sig.confidence,
                "stop_price": sig.stop_price,
                "take_profit": sig.take_profit,
                "time_stop_bars": sig.meta.get("time_stop_bars", 0),
                "trail_mult": sig.meta.get("trail_mult", 1.5),
                "exit_pack": sig.meta.get("exit_pack", "passthrough"),
                "partial_take_profit": sig.meta.get("partial_take_profit"),
                "partial_fraction": sig.meta.get("partial_fraction", 0.0),
            },
        )
