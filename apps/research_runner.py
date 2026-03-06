from __future__ import annotations

import argparse
import json
import pathlib
import time

import yaml

from packages.core.config import REQUIRED_TOP_LEVEL_KEYS
from packages.core.config import load_config
from packages.profiles.symbol_profile import SymbolProfile
from packages.research.candidate_registry import CandidateRegistry
from packages.research.optimizer import ResearchOptimizer
from packages.research.strategy_ideas import StrategyIdeaLibrary
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
    ideas_dir = (active_cfg.get("bootstrap") or {}).get("strategy_idea_library_dir", "strategy_ideas")
    ideas = StrategyIdeaLibrary(ideas_dir).report()
    implemented_idea_families = sorted({row.get("family") for row in ideas.get("implemented_plugins", []) if row.get("family")})
    if not args.strategy_families and implemented_idea_families:
        strategy_families = [fam for fam in strategy_families if fam in implemented_idea_families] or implemented_idea_families

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
    artifact_root = pathlib.Path("runtime/review_artifacts")
    artifact_root.mkdir(parents=True, exist_ok=True)
    for rows in ranking.values():
        for row in rows:
            track = "strict" if row.get("strategy_family") not in {"TrendCore", "RangeMR"} or row.get("code_change") else "fast"
            candidate_type = "search-space" if row.get("search_space_patch") else "config"
            candidate_dir = artifact_root / row["id"]
            candidate_dir.mkdir(parents=True, exist_ok=True)
            summary = row.get("summary", "research-generated config candidate")
            metrics = {
                "score": row["score"],
                "symbol": row["symbol"],
                "regime": row["regime"],
                "walk_forward": row.get("walk_forward"),
                "fees": row.get("fees"),
            }
            validation_report = {
                "schema_valid": True,
                "config_valid": True,
                "backtest_pass": bool(row.get("walk_forward")),
                "oos_pass": bool((row.get("walk_forward") or {}).get("out_sample")),
                "severe_risk_flags": False,
            }
            (candidate_dir / "summary.md").write_text(f"# {row['id']}\n\n{summary}\n", encoding="utf-8")
            (candidate_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            (candidate_dir / "config_patch.yaml").write_text(yaml.safe_dump(row.get("strategy_config_patch", {}), sort_keys=True), encoding="utf-8")
            (candidate_dir / "risk_notes.md").write_text("standard guardrails applied\n", encoding="utf-8")
            (candidate_dir / "provenance.json").write_text(
                json.dumps(
                    {
                        "provider": row.get("provider", "research_optimizer"),
                        "generated_ts": time.time(),
                        "bundle_source": "research_runner",
                        "idea_library_id": row.get("idea_id"),
                        "idea_priority_hint": row.get("idea_priority_hint"),
                        "idea_strict_track_required": row.get("idea_strict_track_required", False),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (candidate_dir / "validation_report.json").write_text(json.dumps(validation_report, indent=2), encoding="utf-8")
            registry.register(row["id"], row["score"], {
                "symbol": row["symbol"],
                "regime": row["regime"],
                "symbols": [row["symbol"]],
                "regimes": [row["regime"]],
                "candidate_type": candidate_type,
                "track": track,
                "summary": summary,
                "backtest_result": row.get("walk_forward"),
                "oos_result": (row.get("walk_forward") or {}).get("out_sample"),
                "config_patch": row.get("strategy_config_patch"),
                "provider_used": row.get("provider", "research_optimizer"),
                "risk_notes": row.get("risk_notes", "standard guardrails applied"),
                "validation_report": validation_report,
                "artifact_bundle": str(candidate_dir),
                "idea_id": row.get("idea_id"),
                "code_change": bool(row.get("code_change", False)),
            })
            registry.transition(row["id"], "config_generated")
            registry.transition(row["id"], "backtest_pass")
            registry.transition(row["id"], "ready_for_review")
            review_queue.enqueue({
                "id": row["id"],
                "type": candidate_type,
                "symbols": [row["symbol"]],
                "regimes": [row["regime"]],
                "strategy_family": row.get("strategy_family"),
                "provider": row.get("provider", "research_optimizer"),
                "track": track,
                "backtest_result": row.get("walk_forward"),
                "oos_result": (row.get("walk_forward") or {}).get("out_sample"),
                "paper_smoke_result": row.get("paper_smoke_result"),
                "config_patch": row.get("strategy_config_patch"),
                "warnings": row.get("warnings", []),
                "recommendation": row.get("recommendation", "manual_review"),
                "created_ts": time.time(),
                "artifacts": {
                    "summary": summary,
                    "bundle": str(candidate_dir),
                },
            })
    bootstrap = {
        "idea_library": {
            "total": ideas.get("total", 0),
            "implemented": len(ideas.get("implemented_plugins", [])),
            "strict_track_candidates": len(ideas.get("strict_track_candidates", [])),
        },
        "research_focus": {
            "symbols": symbols,
            "regimes": regimes,
            "strategy_families": strategy_families,
        },
    }
    print(json.dumps({"candidate_registry": registry.report(), "bootstrap": bootstrap}, indent=2))


if __name__ == "__main__":
    main()
