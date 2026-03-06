from __future__ import annotations

from typing import Dict, List, Tuple

from packages.profiles.symbol_profile import SymbolProfile

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
        symbol_profile: SymbolProfile | None = None,
        current_positions: Dict[str, float] | None = None,
    ) -> DecisionRecord | None:
        if not candidates:
            return None
        scores = {}
        score_components: Dict[str, Dict[str, float]] = {}
        for strategy_name, cfg_name, signal in candidates:
            base = self.base_edge.get(strategy_name, 0.0) + signal.confidence
            spread_cost = cost_proxy.get("spread", 0.0)
            slippage_cost = cost_proxy.get("slippage", 0.0)
            funding_cost = cost_proxy.get("funding", 0.0)
            if symbol_profile:
                funding_cost += abs(symbol_profile.funding_behavior) * 0.5
            corr_penalty = 0.0
            if current_positions:
                same_direction = sum(
                    1
                    for qty in current_positions.values()
                    if qty != 0 and ((qty > 0 and signal.side == "BUY") or (qty < 0 and signal.side == "SELL"))
                )
                corr_penalty = same_direction * 0.01
            profile_penalty = 0.0
            if symbol_profile:
                profile_penalty = max(0.0, 1.0 - symbol_profile.liquidity_signature) * 0.02
            total = base - spread_cost - slippage_cost - funding_cost - exposure_penalty - corr_penalty - profile_penalty
            key = f"{strategy_name}:{cfg_name}"
            scores[key] = round(total, 6)
            score_components[key] = {
                "base": round(base, 6),
                "spread_cost": round(spread_cost, 6),
                "slippage_cost": round(slippage_cost, 6),
                "funding_cost": round(funding_cost, 6),
                "exposure_penalty": round(exposure_penalty, 6),
                "corr_penalty": round(corr_penalty, 6),
                "profile_penalty": round(profile_penalty, 6),
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
            selected_candidate=selected_key,
            selected_strategy=strategy_name,
            selected_config=cfg_name,
            selected_side=sig.side,
            sizing={
                "confidence": sig.confidence,
                "stop_price": sig.stop_price,
                "take_profit": sig.take_profit,
                "time_stop_bars": float(sig.meta.get("time_stop_bars", 0) or 0),
                "score_components": score_components.get(selected_key, {}),
            },
        )
