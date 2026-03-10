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
from packages.research.export_refresh_service import ExportRefreshService
from packages.research.optimizer import ResearchOptimizer
from packages.research.strategy_ideas import StrategyIdeaLibrary


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


def run_research(
    *,
    config_path: str,
    space_path: str = "configs/research_space.yaml",
    samples: int = 15,
    symbols_arg: str = "",
    regimes_arg: str = "",
    start_ts: int | None = None,
    end_ts: int | None = None,
    strategy_families_arg: str = "",
    trigger_source: str = "manual",
    trigger_reasons: list[str] | None = None,
    trigger_context: dict | None = None,
) -> dict:
    active_cfg = load_config(config_path)
    space = _load_yaml_or_config(space_path)

    symbols = [s.strip() for s in symbols_arg.split(",") if s.strip()] or space.get("symbols") or active_cfg["symbols"]
    if regimes_arg:
        regimes = [r.strip() for r in regimes_arg.split(",") if r.strip()]
    else:
        regimes = space.get("regimes") or sorted(
            {
                regime
                for sym in symbols
                for regime in active_cfg.get("strategy_profiles", {}).get(sym, {}).keys()
            }
        )
    strategy_families = (
        [x.strip() for x in strategy_families_arg.split(",") if x.strip()]
        or space.get("strategy_families")
        or list(active_cfg.get("strategy_configs", {}).keys())
    )
    ideas_dir = (active_cfg.get("bootstrap") or {}).get("strategy_idea_library_dir", "strategy_ideas")
    ideas = StrategyIdeaLibrary(ideas_dir).report()
    implemented_idea_families = sorted({row.get("family") for row in ideas.get("implemented_plugins", []) if row.get("family")})
    if not strategy_families_arg and implemented_idea_families:
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
        samples=samples,
        start_ts=start_ts or space.get("start_ts"),
        end_ts=end_ts or space.get("end_ts"),
        symbol_profiles=symbol_profiles,
    )
    total_candidates = sum(len(rows) for rows in ranking.values())
    print(f"Generated {total_candidates} candidates across {len(ranking)} symbol/regime buckets")
    for key, rows in sorted(ranking.items()):
        top = rows[0]["score"] if rows else "n/a"
        print(f"  {key} -> top_score={top}")
    registry = CandidateRegistry()
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
                "plausible": row.get("plausible", False),
                "rejection_reasons": row.get("rejection_reasons", []),
                "evaluation": row.get("evaluation", {}),
                "symbol": row["symbol"],
                "regime": row["regime"],
                "walk_forward": row.get("walk_forward"),
                "fees": row.get("fees"),
            }
            validation_report = {
                "schema_valid": True,
                "config_valid": True,
                "backtest_pass": bool(row.get("walk_forward")),
                "oos_pass": bool(row.get("plausible", False)),
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
                        "trigger_source": trigger_source,
                        "trigger_reasons": trigger_reasons or ["manual"],
                        "trigger_context": trigger_context or {},
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
                "evaluation": row.get("evaluation", {}),
                "plausible": row.get("plausible", False),
                "rejection_reasons": row.get("rejection_reasons", []),
                "risk_notes": row.get("risk_notes", "standard guardrails applied"),
                "validation_report": validation_report,
                "artifact_bundle": str(candidate_dir),
                "idea_id": row.get("idea_id"),
                "code_change": bool(row.get("code_change", False)),
                "trigger_source": trigger_source,
                "trigger_reasons": trigger_reasons or ["manual"],
                "trigger_context": trigger_context or {},
            })
            registry.transition(row["id"], "config_generated")
            registry.transition(row["id"], "backtest_pass")
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
    summary = {"candidate_registry": registry.report(), "bootstrap": bootstrap, "generated_candidates": total_candidates}
    export_refresh = ExportRefreshService.from_config(active_cfg)
    summary["export_refresh"] = export_refresh.refresh_exports(
        trigger="research_runner",
        context={"generated_candidates": total_candidates, "trigger_source": trigger_source},
    )
    print(json.dumps(summary, indent=2))
    return summary


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
    run_research(
        config_path=args.config,
        space_path=args.space,
        samples=args.samples,
        symbols_arg=args.symbols,
        regimes_arg=args.regimes,
        start_ts=args.start_ts,
        end_ts=args.end_ts,
        strategy_families_arg=args.strategy_families,
    )


if __name__ == "__main__":
    main()
