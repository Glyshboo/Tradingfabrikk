from __future__ import annotations

import json
import pathlib
import random
from collections import defaultdict
from copy import deepcopy
from typing import Dict, List

import yaml

from packages.backtest.engine import BacktestResult, CandleBacktester
from packages.data.data_manager import DataManager
from packages.profiles.symbol_profile import SymbolProfile, effective_backtest_costs
from packages.research.strategy_ideas import StrategyIdeaLibrary


class ResearchOptimizer:
    def __init__(self, out_dir: str = "configs/candidates", seed: int = 42) -> None:
        self.out_dir = pathlib.Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._rng = random.Random(seed)

    def _space_params(self, search_space: Dict, strategy_family: str) -> Dict[str, list]:
        families = search_space.get("families", {}) if isinstance(search_space, dict) else {}
        family_cfg = families.get(strategy_family, {}) if isinstance(families, dict) else {}
        params = family_cfg.get("params") if isinstance(family_cfg, dict) else None
        if isinstance(params, dict) and params:
            return {k: v for k, v in params.items() if isinstance(v, list) and v}

        legacy_map = {
            "TrendCore": {
                "atr_stop_mult": search_space.get("atr_stop_mult", [1.5, 2.0, 2.5, 3.0]),
                "time_stop_bars": search_space.get("time_stop_bars", [8, 12, 16, 24]),
            },
            "RangeMR": {
                "rsi_low": search_space.get("rsi_low", [32, 35, 38, 40]),
                "rsi_high": search_space.get("rsi_high", [60, 62, 65, 68]),
                "atr_stop_mult": search_space.get("range_atr_stop_mult", [0.8, 1.0, 1.2]),
                "take_profit_atr_mult": search_space.get("take_profit_atr_mult", [0.1, 0.2, 0.35]),
            },
            "BreakoutRetest": {
                "min_range_compression": search_space.get("br_min_range_compression", [0.15, 0.2, 0.3]),
                "min_trend_slope": search_space.get("br_min_trend_slope", [0.0003, 0.00045, 0.0006]),
                "min_reclaim_distance_atr": search_space.get("br_min_reclaim_distance_atr", [0.01, 0.02, 0.05]),
                "max_retest_distance_atr": search_space.get("br_max_retest_distance_atr", [0.25, 0.35, 0.5]),
                "atr_stop_mult": search_space.get("br_atr_stop_mult", [1.5, 1.8, 2.2]),
                "long_rsi_min": search_space.get("br_long_rsi_min", [50, 52, 55]),
                "short_rsi_max": search_space.get("br_short_rsi_max", [45, 48, 50]),
            },
            "TrendPullback": {
                "min_trend_slope": search_space.get("tp_min_trend_slope", [0.00035, 0.0005, 0.00065]),
                "max_pullback_distance_atr": search_space.get("tp_max_pullback_distance_atr", [0.3, 0.45, 0.6]),
                "max_chase_distance_atr": search_space.get("tp_max_chase_distance_atr", [0.5, 0.75, 1.0]),
                "atr_stop_mult": search_space.get("tp_atr_stop_mult", [1.8, 2.0, 2.4]),
                "long_rsi_pullback_min": search_space.get("tp_long_rsi_pullback_min", [42, 45, 48]),
                "long_rsi_confirm_max": search_space.get("tp_long_rsi_confirm_max", [60, 63, 66]),
                "short_rsi_confirm_min": search_space.get("tp_short_rsi_confirm_min", [34, 37, 40]),
                "short_rsi_pullback_max": search_space.get("tp_short_rsi_pullback_max", [52, 55, 58]),
            },
            "FailedBreakoutFade": {
                "min_failed_breakout_distance_atr": search_space.get("fbf_min_failed_breakout_distance_atr", [0.12, 0.18, 0.25]),
                "min_reversal_slope": search_space.get("fbf_min_reversal_slope", [0.00025, 0.00035, 0.0005]),
                "min_range_compression": search_space.get("fbf_min_range_compression", [0.1, 0.15, 0.25]),
                "atr_stop_mult": search_space.get("fbf_atr_stop_mult", [1.2, 1.4, 1.8]),
                "fade_short_rsi_min": search_space.get("fbf_fade_short_rsi_min", [54, 56, 60]),
                "fade_long_rsi_max": search_space.get("fbf_fade_long_rsi_max", [40, 44, 48]),
            },
        }
        return legacy_map.get(strategy_family, legacy_map["TrendCore"])

    def _sample_strategy_config(self, strategy_family: str, search_space: Dict) -> Dict:
        params = self._space_params(search_space, strategy_family)
        cfg = {k: self._rng.choice(v) for k, v in params.items()}
        shared = search_space.get("shared_params", {}) if isinstance(search_space, dict) else {}
        if not isinstance(shared, dict):
            shared = {}
        base_conf = shared.get("base_confidence") or search_space.get("base_confidence") or [0.5, 0.55, 0.58, 0.62]
        cfg["base_confidence"] = self._rng.choice(base_conf)
        return cfg

    def _family_priority_params(self, search_space: Dict, strategy_family: str) -> list[str]:
        family_cfg = ((search_space.get("families") or {}).get(strategy_family) or {}) if isinstance(search_space, dict) else {}
        from_family_cfg = family_cfg.get("mutation_priority") if isinstance(family_cfg, dict) else None
        mutation_cfg = search_space.get("mutation", {}) if isinstance(search_space, dict) else {}
        from_mutation_cfg = (mutation_cfg.get("mutation_family_priority_params") or {}).get(strategy_family, [])
        merged = []
        for key in list(from_family_cfg or []) + list(from_mutation_cfg or []):
            if isinstance(key, str) and key not in merged:
                merged.append(key)
        return merged

    def _sample_combination(self, strategy_family: str, search_space: Dict) -> Dict:
        composition_cfg = search_space.get("composition", {}) if isinstance(search_space, dict) else {}
        filter_packs = composition_cfg.get("filter_packs", ["safe"]) if isinstance(composition_cfg, dict) else ["safe"]
        exit_packs = composition_cfg.get("exit_packs", ["passthrough"]) if isinstance(composition_cfg, dict) else ["passthrough"]
        optional_modules = composition_cfg.get("optional_filter_modules", []) if isinstance(composition_cfg, dict) else []
        family_rules = composition_cfg.get("family_rules", {}).get(strategy_family, {}) if isinstance(composition_cfg, dict) else {}
        allowed_filters = family_rules.get("filter_packs") if isinstance(family_rules, dict) else None
        allowed_exits = family_rules.get("exit_packs") if isinstance(family_rules, dict) else None

        picked_filter = self._rng.choice(allowed_filters or filter_packs or ["safe"])
        picked_exit = self._rng.choice(allowed_exits or exit_packs or ["passthrough"])
        module_count = min(len(optional_modules), 1 if self._rng.random() < 0.75 else 2)
        modules = self._rng.sample(optional_modules, k=module_count) if optional_modules and module_count else []
        return {
            "entry_family": strategy_family,
            "filter_pack": picked_filter,
            "filter_modules": modules,
            "exit_pack": picked_exit,
        }

    def _build_candidate_config(self, strategy_family: str, search_space: Dict) -> Dict:
        cfg = self._sample_strategy_config(strategy_family, search_space)
        cfg["composition"] = self._sample_combination(strategy_family, search_space)
        return cfg

    def _candidate_kind(self, strategy_family: str, composition: Dict, search_space: Dict, parent: Dict | None = None) -> str:
        incubation = search_space.get("incubation", {}) if isinstance(search_space, dict) else {}
        established = set(incubation.get("established_entry_families", ["TrendCore", "RangeMR"]))
        if strategy_family not in established:
            return "new_family_candidate"
        if parent:
            if composition != parent:
                return "combination_candidate"
            return "config_tweak"
        if composition.get("filter_pack") != "safe" or composition.get("exit_pack") != "passthrough" or composition.get("filter_modules"):
            return "combination_candidate"
        return "config_tweak"

    def _mutate_candidate(self, candidate: Dict, search_space: Dict) -> Dict | None:
        mutation_cfg = search_space.get("mutation", {}) if isinstance(search_space, dict) else {}
        if not candidate.get("plausible"):
            return None
        if float(candidate.get("score", 0.0)) < float(mutation_cfg.get("plausible_min_score", 0.0)):
            return None

        cfg = deepcopy(candidate.get("strategy_config") or {})
        family = candidate.get("strategy_family", "TrendCore")
        params = self._space_params(search_space, family)
        change_keys = [k for k in params.keys() if k in cfg] + ["base_confidence"]
        if not change_keys:
            return None

        established = set((search_space.get("incubation", {}) or {}).get("established_entry_families", ["TrendCore", "RangeMR"]))
        mutation_type = "config_tweak"
        if family in established and self._rng.random() < float(mutation_cfg.get("mutate_composition_probability", 0.18)):
            mutation_type = "combination_tweak"
        elif family in established and self._rng.random() < float(mutation_cfg.get("allow_new_family_candidate_probability", 0.0)):
            mutation_type = "new_family_candidate"

        priority = [k for k in self._family_priority_params(search_space, family) if k in change_keys]
        boost_prob = float(mutation_cfg.get("family_priority_boost_probability", 0.75))
        mutation_pool = priority if priority and self._rng.random() < boost_prob else change_keys
        max_changes = max(1, int(mutation_cfg.get("max_parameter_changes", 2)))
        change_count = self._rng.randint(1, min(max_changes, len(mutation_pool)))
        changed_keys: list[str] = []
        for key in self._rng.sample(mutation_pool, k=change_count):
            options = list(search_space.get("shared_params", {}).get(key, [])) if key == "base_confidence" else list(params.get(key, []))
            if not options:
                continue
            current = cfg.get(key)
            if current in options and len(options) >= 3:
                idx = options.index(current)
                left = options[max(0, idx - 1)]
                right = options[min(len(options) - 1, idx + 1)]
                neighborhood = [x for x in {left, right, current} if x != current]
                cfg[key] = self._rng.choice(neighborhood or [x for x in options if x != current] or options)
            else:
                cfg[key] = self._rng.choice([x for x in options if x != current] or options)
            changed_keys.append(key)

        keep_comp_prob = float(mutation_cfg.get("keep_composition_probability", 0.85))
        if mutation_type == "combination_tweak" and self._rng.random() > keep_comp_prob:
            cfg["composition"] = self._sample_combination(family, search_space)
        cfg["mutation_trace"] = {
            "mutation_type": mutation_type,
            "family_priority_used": bool(priority and mutation_pool == priority),
            "changed_keys": changed_keys,
        }
        return cfg

    def _as_payload(self, res: BacktestResult) -> Dict:
        return {
            "trades": res.trades,
            "pnl": res.pnl,
            "gross_pnl": res.gross_pnl,
            "total_cost": res.total_cost,
            "cost_to_gross_ratio": round(res.total_cost / max(abs(res.gross_pnl), 1e-9), 6),
            "sharpe_like": res.sharpe_like,
            "max_drawdown": res.max_drawdown,
            "turnover": res.turnover,
        }

    def _strategy_composition_descriptor(self, strategy_family: str, cfg: Dict) -> Dict:
        composition = cfg.get("composition", {}) if isinstance(cfg, dict) else {}
        if isinstance(composition, dict) and composition.get("entry_family"):
            return {
                "entry_family": composition.get("entry_family"),
                "filter_pack": composition.get("filter_pack", "none"),
                "filter_modules": composition.get("filter_modules", []),
                "exit_pack": composition.get("exit_pack", "passthrough"),
            }
        return {
            "entry_family": strategy_family,
            "filter_pack": "safe",
            "filter_modules": [],
            "exit_pack": "passthrough",
        }

    def _evaluate_candidate(
        self,
        in_sample: BacktestResult,
        out_sample: BacktestResult,
        out_sample_no_cost: BacktestResult,
        bars: int,
        cfg: Dict,
        thresholds: Dict,
        strategy_family: str | None = None,
    ) -> Dict:
        family_overrides = (thresholds.get("family_threshold_overrides") or {}).get(strategy_family or "", {}) if isinstance(thresholds, dict) else {}
        merged_thresholds = {**(thresholds or {}), **(family_overrides if isinstance(family_overrides, dict) else {})}
        min_in_sample_trades = int(merged_thresholds.get("min_in_sample_trades", 4))
        min_out_sample_trades = int(merged_thresholds.get("min_out_sample_trades", 4))
        min_out_sample_pnl = float(merged_thresholds.get("min_out_sample_pnl", 0.0))
        min_out_sample_sharpe = float(merged_thresholds.get("min_out_sample_sharpe", -0.02))
        min_oos_is_pnl_ratio = float(merged_thresholds.get("min_oos_is_pnl_ratio", 0.15))
        max_turnover_per_bar = float(merged_thresholds.get("max_turnover_per_bar", 350.0))
        max_cost_to_gross_ratio = float(merged_thresholds.get("max_cost_to_gross_ratio", 0.85))
        max_confidence = float(merged_thresholds.get("max_base_confidence", 0.75))

        reasons: list[str] = []
        turnover_per_bar = out_sample.turnover / max(1.0, float(bars))
        cost_to_gross_ratio = out_sample.total_cost / max(abs(out_sample.gross_pnl), 1e-9)

        if in_sample.trades < min_in_sample_trades:
            reasons.append("insufficient_in_sample_trades")
        if out_sample.trades < min_out_sample_trades:
            reasons.append("insufficient_out_sample_trades")
        if out_sample.pnl <= min_out_sample_pnl:
            reasons.append("weak_or_negative_out_sample_pnl")
        if out_sample.sharpe_like < min_out_sample_sharpe:
            reasons.append("weak_out_sample_sharpe")
        if turnover_per_bar > max_turnover_per_bar:
            reasons.append("excessive_turnover")
        if cost_to_gross_ratio > max_cost_to_gross_ratio:
            reasons.append("cost_dominates_gross_edge")
        if cfg.get("base_confidence", 0.0) > max_confidence:
            reasons.append("base_confidence_out_of_bounds")

        oos_is_pnl_ratio = out_sample.pnl / max(abs(in_sample.pnl), 1.0)
        if oos_is_pnl_ratio < min_oos_is_pnl_ratio:
            reasons.append("weak_oos_vs_is_robustness")

        overfit_gap = max(0.0, in_sample.sharpe_like - out_sample.sharpe_like)
        stability_gap = abs(in_sample.sharpe_like - out_sample.sharpe_like)
        drawdown_penalty = out_sample.max_drawdown / max(abs(out_sample.pnl), 1.0)
        cost_drag = max(0.0, out_sample_no_cost.pnl - out_sample.pnl)
        cost_drag_ratio = cost_drag / max(abs(out_sample_no_cost.pnl), 1.0)

        oos_score = (out_sample.pnl * 0.09) + (out_sample.sharpe_like * 3.2)
        is_support_score = (in_sample.pnl * 0.02) + (in_sample.sharpe_like * 0.6)
        stability_score = 1.4 - (stability_gap * 2.0)
        trade_quality_score = min(out_sample.trades, 40) / 16.0

        penalty = (
            (overfit_gap * 2.4)
            + (drawdown_penalty * 0.45)
            + (max(0.0, turnover_per_bar - 120.0) * 0.004)
            + (cost_drag_ratio * 2.5)
            + (cost_to_gross_ratio * 1.0)
            + (cfg.get("base_confidence", 0.0) * 0.45)
        )
        score = (oos_score * 0.72) + (is_support_score * 0.28) + stability_score + trade_quality_score - penalty

        plausible = not reasons
        if not plausible:
            score -= 50.0 + (2.5 * len(reasons))

        return {
            "score": round(score, 6),
            "plausible": plausible,
            "rejection_reasons": reasons,
            "components": {
                "oos_score": round(oos_score, 6),
                "is_support_score": round(is_support_score, 6),
                "stability_score": round(stability_score, 6),
                "trade_quality_score": round(trade_quality_score, 6),
                "penalty": round(penalty, 6),
                "overfit_gap": round(overfit_gap, 6),
                "stability_gap": round(stability_gap, 6),
                "drawdown_penalty": round(drawdown_penalty, 6),
                "turnover_per_bar": round(turnover_per_bar, 6),
                "cost_drag_ratio": round(cost_drag_ratio, 6),
                "cost_to_gross_ratio": round(cost_to_gross_ratio, 6),
                "oos_is_pnl_ratio": round(oos_is_pnl_ratio, 6),
            },
            "minimum_requirements": {
                "min_in_sample_trades": min_in_sample_trades,
                "min_out_sample_trades": min_out_sample_trades,
                "min_out_sample_pnl": min_out_sample_pnl,
                "min_out_sample_sharpe": min_out_sample_sharpe,
                "min_oos_is_pnl_ratio": min_oos_is_pnl_ratio,
                "max_turnover_per_bar": max_turnover_per_bar,
                "max_cost_to_gross_ratio": max_cost_to_gross_ratio,
                "max_base_confidence": max_confidence,
            },
            "family_overrides": family_overrides if isinstance(family_overrides, dict) else {},
        }

    def _onboarding_assessment(
        self,
        *,
        candidate_kind: str,
        strategy_family: str,
        composition: Dict,
        evaluation: Dict,
        out_sample: BacktestResult,
        search_space: Dict,
        mutation_trace: Dict | None = None,
        parent: Dict | None = None,
    ) -> Dict:
        incubation = search_space.get("incubation", {}) if isinstance(search_space, dict) else {}
        established = set(incubation.get("established_entry_families", ["TrendCore", "RangeMR"]))

        filter_modules = list(composition.get("filter_modules") or [])
        filter_pack = str(composition.get("filter_pack") or "safe")
        exit_pack = str(composition.get("exit_pack") or "passthrough")
        filter_complexity = len(filter_modules) + (0 if filter_pack in {"none", "safe"} else 1)
        exit_complexity = 0 if exit_pack == "passthrough" else 1

        changed_keys = list((mutation_trace or {}).get("changed_keys") or [])
        mutation_distance = 0.0
        if changed_keys:
            mutation_distance = min(1.0, len(changed_keys) / 4.0)
            if parent and composition != (parent.get("strategy_composition") or parent.get("composition") or {}):
                mutation_distance = min(1.0, mutation_distance + 0.35)

        components = evaluation.get("components", {}) if isinstance(evaluation, dict) else {}
        plausibility_penalty = 0.0 if evaluation.get("plausible", False) else 0.45
        oos_robustness = max(0.0, min(1.0, float(components.get("oos_is_pnl_ratio", 0.0)) / 0.8))
        cost_drag = max(
            float(components.get("cost_drag_ratio", 0.0)),
            float(components.get("cost_to_gross_ratio", 0.0)),
        )
        evidence_strength = min(1.0, out_sample.trades / 12.0)
        strong_parent = bool(parent and parent.get("plausible") and float(parent.get("score", 0.0)) > 0.0)

        score = 0.55
        score += 0.12 if candidate_kind == "config_tweak" else -0.08
        score += 0.08 if strategy_family in established else -0.18
        score -= min(0.2, filter_complexity * 0.05)
        score -= exit_complexity * 0.05
        score -= mutation_distance * 0.18
        score += 0.07 if strong_parent else -0.05
        score += (oos_robustness - 0.5) * 0.3
        score -= min(0.22, cost_drag * 0.35)
        score += (evidence_strength - 0.5) * 0.22
        score -= plausibility_penalty
        score = max(0.0, min(1.0, score))

        trust_tier = "low"
        if score >= 0.7:
            trust_tier = "high"
        elif score >= 0.5:
            trust_tier = "medium"

        novelty_class = "minor_tweak"
        if candidate_kind in {"new_family_candidate", "combination_candidate"} or mutation_distance >= 0.6:
            novelty_class = "major_new_idea"
        elif mutation_distance >= 0.25 or filter_complexity > 1 or exit_complexity > 0:
            novelty_class = "combination_tweak"

        return {
            "trust_score": round(score, 6),
            "trust_tier": trust_tier,
            "onboarding_profile": "fast_track" if score >= 0.68 and candidate_kind == "config_tweak" else "strict_track",
            "complexity_summary": {
                "filter_complexity": filter_complexity,
                "exit_complexity": exit_complexity,
                "mutation_distance": round(mutation_distance, 6),
                "complexity_class": "high" if (filter_complexity + exit_complexity) >= 3 or mutation_distance > 0.6 else "standard",
            },
            "novelty_summary": {
                "novelty_class": novelty_class,
                "candidate_kind": candidate_kind,
                "new_family": strategy_family not in established,
                "strong_parent": strong_parent,
            },
            "progression_guidance": {
                "recommended_min_challenger_evaluations": 2 if score >= 0.68 else 4,
                "recommended_smoke_strictness": 0 if score >= 0.68 else 1,
                "prefer_early_revalidation": score < 0.42,
            },
            "audit_components": {
                "candidate_kind": candidate_kind,
                "family_known": strategy_family in established,
                "filter_complexity": filter_complexity,
                "exit_complexity": exit_complexity,
                "mutation_distance": round(mutation_distance, 6),
                "strong_parent": strong_parent,
                "oos_robustness": round(oos_robustness, 6),
                "cost_drag": round(cost_drag, 6),
                "evidence_strength": round(evidence_strength, 6),
                "plausibility_penalty": plausibility_penalty,
                "rejection_context": list(evaluation.get("rejection_reasons") or []),
            },
        }

    def random_search(
        self,
        search_space: Dict,
        symbols: List[str],
        regimes: List[str],
        strategy_families: List[str],
        samples: int = 10,
        start_ts: int | None = None,
        end_ts: int | None = None,
        symbol_profiles: Dict[str, SymbolProfile] | None = None,
    ) -> Dict[str, List[Dict]]:
        bt = CandleBacktester()
        data_manager = DataManager(symbols=symbols)
        idea_lib = StrategyIdeaLibrary()
        idea_rows = idea_lib.load()
        by_tuple: Dict[tuple[str, str], List[Dict]] = defaultdict(list)
        thresholds = search_space.get("evaluation", {})

        families_from_space = list((search_space.get("composition", {}) or {}).get("entry_families", []))
        selected_families = [fam for fam in (families_from_space or strategy_families) if fam in strategy_families]
        selected_families = selected_families or strategy_families

        mutation_cfg = search_space.get("mutation", {}) if isinstance(search_space, dict) else {}
        top_k = int(mutation_cfg.get("top_k_seeds", 2))
        refinements_per_seed = int(mutation_cfg.get("refinements_per_seed", 2))

        for symbol in symbols:
            for regime in regimes:
                candles = data_manager.load_historical_candles(
                    symbol=symbol,
                    regime=regime,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    bars=int(search_space.get("bars", 400)),
                )
                if len(candles) < 8:
                    continue

                profile = (symbol_profiles or {}).get(symbol)
                fee_bps, slippage_bps = effective_backtest_costs(profile)

                bucket_rows: List[Dict] = []
                sequence = 0
                for strategy_family in selected_families:
                    for _ in range(samples):
                        cfg = self._build_candidate_config(strategy_family, search_space)
                        in_sample, out_sample = bt.run_walk_forward(
                            candles,
                            fee_bps=fee_bps,
                            slippage_bps=slippage_bps,
                            strategy_family=strategy_family,
                            strategy_config=cfg,
                        )
                        _, out_sample_no_cost = bt.run_walk_forward(
                            candles,
                            fee_bps=0.0,
                            slippage_bps=0.0,
                            strategy_family=strategy_family,
                            strategy_config=cfg,
                        )
                        eval_result = self._evaluate_candidate(
                            in_sample=in_sample,
                            out_sample=out_sample,
                            out_sample_no_cost=out_sample_no_cost,
                            bars=len(candles),
                            cfg=cfg,
                            thresholds=thresholds,
                            strategy_family=strategy_family,
                        )
                        config_name = f"{symbol.lower()}_{regime.lower()}_{strategy_family.lower()}_{sequence}"
                        sequence += 1

                        composition = self._strategy_composition_descriptor(strategy_family, cfg)
                        candidate_kind = self._candidate_kind(strategy_family, composition, search_space)
                        matching_idea = next(
                            (
                                x
                                for x in idea_rows
                                if x.get("family") == strategy_family and regime in (x.get("typical_market_regimes") or [])
                            ),
                            None,
                        )
                        context_ideas = idea_lib.rank_for_symbol_regime(symbol=symbol, regime=regime, limit=4)
                        payload = {
                            "id": config_name,
                            "symbol": symbol,
                            "regime": regime,
                            "strategy_family": strategy_family,
                            "strategy_composition": composition,
                            "candidate_kind": candidate_kind,
                            "score": eval_result["score"],
                            "plausible": eval_result["plausible"],
                            "rejection_reasons": eval_result["rejection_reasons"],
                            "evaluation": eval_result,
                            "pnl": out_sample.pnl,
                            "walk_forward": {
                                "in_sample": self._as_payload(in_sample),
                                "out_sample": self._as_payload(out_sample),
                                "out_sample_no_cost": self._as_payload(out_sample_no_cost),
                            },
                            "fees": {"fee_bps": round(fee_bps, 6), "slippage_bps": round(slippage_bps, 6)},
                            "strategy_config": cfg,
                            "mutation_type": "seed",
                            "mutation_trace": {"mutation_type": "seed", "changed_keys": []},
                            "strategy_config_patch": {strategy_family: {config_name: cfg}},
                            "strategy_profile_patch": {symbol: {regime: [[strategy_family, config_name]]}},
                            "idea_id": matching_idea.get("id") if matching_idea else None,
                            "idea_priority_hint": matching_idea.get("priority_hint") if matching_idea else None,
                            "idea_strict_track_required": bool(matching_idea.get("strict_track_required", False)) if matching_idea else False,
                            "idea_context_top": context_ideas,
                        }
                        payload["onboarding_assessment"] = self._onboarding_assessment(
                            candidate_kind=candidate_kind,
                            strategy_family=strategy_family,
                            composition=composition,
                            evaluation=eval_result,
                            out_sample=out_sample,
                            search_space=search_space,
                            mutation_trace=payload.get("mutation_trace"),
                        )
                        bucket_rows.append(payload)

                seeds = sorted([x for x in bucket_rows if x.get("plausible")], key=lambda x: x.get("score", -1e9), reverse=True)[:top_k]
                for seed in seeds:
                    for refine_idx in range(refinements_per_seed):
                        mut_cfg = self._mutate_candidate(seed, search_space)
                        if not mut_cfg:
                            continue
                        family = seed["strategy_family"]
                        in_sample, out_sample = bt.run_walk_forward(
                            candles,
                            fee_bps=fee_bps,
                            slippage_bps=slippage_bps,
                            strategy_family=family,
                            strategy_config=mut_cfg,
                        )
                        _, out_sample_no_cost = bt.run_walk_forward(
                            candles,
                            fee_bps=0.0,
                            slippage_bps=0.0,
                            strategy_family=family,
                            strategy_config=mut_cfg,
                        )
                        eval_result = self._evaluate_candidate(
                            in_sample=in_sample,
                            out_sample=out_sample,
                            out_sample_no_cost=out_sample_no_cost,
                            bars=len(candles),
                            cfg=mut_cfg,
                            thresholds=thresholds,
                            strategy_family=family,
                        )
                        config_name = f"{seed['id']}_mut{refine_idx}"
                        composition = self._strategy_composition_descriptor(family, mut_cfg)
                        candidate_kind = self._candidate_kind(family, composition, search_space, parent=seed.get("strategy_composition"))
                        payload = {
                            **seed,
                            "id": config_name,
                            "strategy_composition": composition,
                            "candidate_kind": candidate_kind,
                            "mutation_source_id": seed["id"],
                            "score": eval_result["score"],
                            "plausible": eval_result["plausible"],
                            "rejection_reasons": eval_result["rejection_reasons"],
                            "evaluation": eval_result,
                            "pnl": out_sample.pnl,
                            "strategy_config": mut_cfg,
                            "mutation_type": (mut_cfg.get("mutation_trace") or {}).get("mutation_type", "config_tweak"),
                            "mutation_trace": mut_cfg.get("mutation_trace", {}),
                            "strategy_config_patch": {family: {config_name: mut_cfg}},
                            "strategy_profile_patch": {symbol: {regime: [[family, config_name]]}},
                            "walk_forward": {
                                "in_sample": self._as_payload(in_sample),
                                "out_sample": self._as_payload(out_sample),
                                "out_sample_no_cost": self._as_payload(out_sample_no_cost),
                            },
                        }
                        payload["onboarding_assessment"] = self._onboarding_assessment(
                            candidate_kind=candidate_kind,
                            strategy_family=family,
                            composition=composition,
                            evaluation=eval_result,
                            out_sample=out_sample,
                            search_space=search_space,
                            mutation_trace=payload.get("mutation_trace"),
                            parent=seed,
                        )
                        bucket_rows.append(payload)

                by_tuple[(symbol, regime)].extend(bucket_rows)
                for row in bucket_rows:
                    outfile = self.out_dir / f"{row['id']}.json"
                    outfile.write_text(json.dumps(row, indent=2), encoding="utf-8")

        ranking = {}
        for key, rows in by_tuple.items():
            symbol, regime = key
            sorted_rows = sorted(
                rows,
                key=lambda x: (x.get("plausible", False), x["score"], x.get("walk_forward", {}).get("out_sample", {}).get("pnl", 0.0)),
                reverse=True,
            )
            ranking[f"{symbol}:{regime}"] = sorted_rows

        (self.out_dir / "ranking.json").write_text(json.dumps(ranking, indent=2), encoding="utf-8")
        (self.out_dir / "ranking.yaml").write_text(yaml.safe_dump(ranking, sort_keys=True), encoding="utf-8")
        return ranking
