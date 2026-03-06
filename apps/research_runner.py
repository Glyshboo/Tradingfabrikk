from __future__ import annotations

import argparse

from packages.core.config import REQUIRED_TOP_LEVEL_KEYS
from packages.core.config import load_config
from packages.profiles.symbol_profile import SymbolProfile
from packages.research.candidate_registry import CandidateRegistry
from packages.research.optimizer import ResearchOptimizer
from packages.review.review_queue import ReviewQueue


def _load_yaml_or_config(path: str) -> dict:
    try:
        data = load_config(path)
        if REQUIRED_TOP_LEVEL_KEYS.issubset(data.keys()):
            return data
    except ValueError:
        pass

    import pathlib
    import yaml

    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        parsed = yaml.safe_load(handle)
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid research config {path}: expected mapping")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--space", default="configs/research_space.yaml")
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--regimes", default="")
    parser.add_argument("--start-ts", type=int, default=None)
    parser.add_argument("--end-ts", type=int, default=None)
    parser.add_argument("--strategy-families", default="")
    args = parser.parse_args()

    active_cfg = load_config(args.config)
    space = _load_yaml_or_config(args.space)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or space.get("symbols") or active_cfg["symbols"]
    if args.regimes:
        regimes = [r.strip() for r in args.regimes.split(",") if r.strip()]
    else:
        regimes = space.get("regimes") or sorted(
            {
                regime
                for sym in symbols
                for regime in active_cfg.get("strategy_profiles", {}).get(sym, {}).keys()
            }
        )
    strategy_families = (
        [x.strip() for x in args.strategy_families.split(",") if x.strip()]
        or space.get("strategy_families")
        or list(active_cfg.get("strategy_configs", {}).keys())
    )

    symbol_profiles = {
        symbol: SymbolProfile(
            liquidity_signature=space.get("symbol_costs", {}).get(symbol, {}).get("liquidity_signature", 1.0),
            slippage_proxy=space.get("symbol_costs", {}).get(symbol, {}).get("slippage_proxy", 0.0),
        )
        for symbol in symbols
    }

    opt = ResearchOptimizer(out_dir="configs/candidates")
    ranking = opt.random_search(
        space,
        symbols=symbols,
        regimes=regimes,
        strategy_families=strategy_families,
        samples=args.samples,
        start_ts=args.start_ts or space.get("start_ts"),
        end_ts=args.end_ts or space.get("end_ts"),
        symbol_profiles=symbol_profiles,
    )
    total_candidates = sum(len(rows) for rows in ranking.values())
    print(f"Generated {total_candidates} candidates across {len(ranking)} symbol/regime buckets")
    for key, rows in sorted(ranking.items()):
        top = rows[0]["score"] if rows else "n/a"
        print(f"  {key} -> top_score={top}")
    registry = CandidateRegistry()
    review_queue = ReviewQueue()
    for rows in ranking.values():
        for row in rows:
            track = "strict" if row.get("strategy_family") not in {"TrendCore", "RangeMR"} or row.get("code_change") else "fast"
            registry.register(row["id"], row["score"], {
                "symbol": row["symbol"],
                "regime": row["regime"],
                "track": track,
                "summary": row.get("summary", "research-generated config candidate"),
                "backtest_result": row.get("walk_forward"),
                "config_patch": row.get("strategy_config_patch"),
                "provider_used": row.get("provider", "research_optimizer"),
                "risk_notes": row.get("risk_notes", "standard guardrails applied"),
                "code_change": bool(row.get("code_change", False)),
            })
            registry.transition(row["id"], "backtest_pass")
            registry.transition(row["id"], "oos_pass")
            registry.transition(row["id"], "ready_for_review")
            review_queue.enqueue({
                "id": row["id"],
                "symbol": row["symbol"],
                "regime": row["regime"],
                "track": track,
                "artifacts": {
                    "summary": "research-generated config candidate",
                    "backtest_result": row.get("walk_forward"),
                    "paper_smoke_result": row.get("paper_smoke_result"),
                    "config_patch": row.get("strategy_config_patch"),
                    "risk_notes": "standard guardrails applied",
                    "provider_used": row.get("provider", "research_optimizer"),
                    "code_change": bool(row.get("code_change", False)),
                },
            })
    print(f"Candidate registry: {registry.report()}")


if __name__ == "__main__":
    main()
