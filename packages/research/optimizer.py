from __future__ import annotations

import json
import pathlib
import random
from collections import defaultdict
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

    def _sample_strategy_config(self, strategy_family: str, search_space: Dict) -> Dict:
        if strategy_family == "RangeMR":
            return {
                "rsi_low": self._rng.choice(search_space.get("rsi_low", [32, 35, 38, 40])),
                "rsi_high": self._rng.choice(search_space.get("rsi_high", [60, 62, 65, 68])),
                "atr_stop_mult": self._rng.choice(search_space.get("range_atr_stop_mult", [0.8, 1.0, 1.2])),
                "take_profit_atr_mult": self._rng.choice(search_space.get("take_profit_atr_mult", [0.1, 0.2, 0.35])),
                "base_confidence": self._rng.choice(search_space.get("base_confidence", [0.5, 0.55, 0.58, 0.62])),
            }
        return {
            "atr_stop_mult": self._rng.choice(search_space.get("atr_stop_mult", [1.5, 2.0, 2.5, 3.0])),
            "time_stop_bars": self._rng.choice(search_space.get("time_stop_bars", [8, 12, 16, 24])),
            "base_confidence": self._rng.choice(search_space.get("base_confidence", [0.5, 0.55, 0.58, 0.62])),
        }

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

    def _evaluate_candidate(
        self,
        in_sample: BacktestResult,
        out_sample: BacktestResult,
        out_sample_no_cost: BacktestResult,
        bars: int,
        cfg: Dict,
        thresholds: Dict,
    ) -> Dict:
        min_in_sample_trades = int(thresholds.get("min_in_sample_trades", 4))
        min_out_sample_trades = int(thresholds.get("min_out_sample_trades", 4))
        min_out_sample_pnl = float(thresholds.get("min_out_sample_pnl", 0.0))
        min_out_sample_sharpe = float(thresholds.get("min_out_sample_sharpe", -0.02))
        min_oos_is_pnl_ratio = float(thresholds.get("min_oos_is_pnl_ratio", 0.15))
        max_turnover_per_bar = float(thresholds.get("max_turnover_per_bar", 350.0))
        max_cost_to_gross_ratio = float(thresholds.get("max_cost_to_gross_ratio", 0.85))
        max_confidence = float(thresholds.get("max_base_confidence", 0.75))

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

                for strategy_family in strategy_families:
                    for i in range(samples):
                        cfg = self._sample_strategy_config(strategy_family, search_space)
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
                        )

                        config_name = f"{symbol.lower()}_{regime.lower()}_{strategy_family.lower()}_{i}"
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
                            "strategy_config_patch": {strategy_family: {config_name: cfg}},
                            "strategy_profile_patch": {symbol: {regime: [[strategy_family, config_name]]}},
                            "idea_id": matching_idea.get("id") if matching_idea else None,
                            "idea_priority_hint": matching_idea.get("priority_hint") if matching_idea else None,
                            "idea_strict_track_required": bool(matching_idea.get("strict_track_required", False)) if matching_idea else False,
                            "idea_context_top": context_ideas,
                        }
                        by_tuple[(symbol, regime)].append(payload)
                        outfile = self.out_dir / f"{config_name}.json"
                        outfile.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
