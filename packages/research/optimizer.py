from __future__ import annotations

import json
import pathlib
import random
from collections import defaultdict
from typing import Dict, List

import yaml

from packages.backtest.engine import CandleBacktester
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
                "rsi_low": self._rng.choice(search_space.get("rsi_low", [35, 40])),
                "rsi_high": self._rng.choice(search_space.get("rsi_high", [60, 65])),
                "base_confidence": self._rng.choice(search_space["base_confidence"]),
            }
        return {
            "atr_stop_mult": self._rng.choice(search_space["atr_stop_mult"]),
            "time_stop_bars": self._rng.choice(search_space["time_stop_bars"]),
            "base_confidence": self._rng.choice(search_space["base_confidence"]),
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
                        in_sample, out_sample = bt.run_walk_forward(candles, fee_bps=fee_bps, slippage_bps=slippage_bps, strategy_family=strategy_family, strategy_config=cfg)
                        res = out_sample
                        shape_penalty = cfg.get("atr_stop_mult", 1.0) * 0.01 if strategy_family == "TrendCore" else 0.004
                        score = res.sharpe_like + cfg["base_confidence"] - shape_penalty
                        config_name = f"{symbol.lower()}_{regime.lower()}_{strategy_family.lower()}_{i}"
                        matching_idea = next(
                            (
                                x for x in idea_rows
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
                            "score": round(score, 6),
                            "pnl": res.pnl,
                            "walk_forward": {
                                "in_sample": {"trades": in_sample.trades, "pnl": in_sample.pnl, "sharpe_like": in_sample.sharpe_like},
                                "out_sample": {"trades": out_sample.trades, "pnl": out_sample.pnl, "sharpe_like": out_sample.sharpe_like},
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
            sorted_rows = sorted(rows, key=lambda x: x["score"], reverse=True)
            ranking[f"{symbol}:{regime}"] = sorted_rows

        (self.out_dir / "ranking.json").write_text(json.dumps(ranking, indent=2), encoding="utf-8")
        (self.out_dir / "ranking.yaml").write_text(yaml.safe_dump(ranking, sort_keys=True), encoding="utf-8")
        return ranking
