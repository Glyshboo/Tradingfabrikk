from __future__ import annotations

from typing import Dict, List, Tuple

from packages.core.models import DecisionRecord, Regime, StrategySignal


class StrategySelector:
    def __init__(self, base_edge: Dict[str, float]):
        self.base_edge = base_edge

    def select(
        self,
        symbol: str,
        regime: Regime,
        candidates: List[Tuple[str, str, StrategySignal]],
        cost_proxy: Dict[str, float],
        exposure_penalty: float,
    ) -> DecisionRecord | None:
        if not candidates:
            return None
        scores = {}
        for strategy_name, cfg_name, signal in candidates:
            base = self.base_edge.get(strategy_name, 0.0) + signal.confidence
            cost = cost_proxy.get("spread", 0.0) + cost_proxy.get("slippage", 0.0) + cost_proxy.get("funding", 0.0)
            total = base - cost - exposure_penalty
            scores[f"{strategy_name}:{cfg_name}"] = round(total, 6)

        selected_key = max(scores, key=scores.get)
        strategy_name, cfg_name = selected_key.split(":", 1)
        sig = [c[2] for c in candidates if c[0] == strategy_name and c[1] == cfg_name][0]
        return DecisionRecord(
            symbol=symbol,
            regime=regime.value,
            eligible_strategies=[f"{c[0]}:{c[1]}" for c in candidates],
            score_breakdown=scores,
            selected_strategy=strategy_name,
            selected_config=cfg_name,
            sizing={"confidence": sig.confidence},
        )
