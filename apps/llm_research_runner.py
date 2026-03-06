from __future__ import annotations

import argparse
import json
import pathlib
import time

from packages.core.config import load_config
from packages.core.state_store import EngineStateStore
from packages.llm.research import LLMResearchService
from packages.research.candidate_registry import CandidateRegistry
from packages.research.strategy_ideas import StrategyIdeaLibrary
from packages.review.review_queue import ReviewQueue


def _compact_research_bundle(status_file: str, ideas_dir: str = "strategy_ideas") -> dict:
    status_path = pathlib.Path(status_file)
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    candidate_report = CandidateRegistry().report()
    queue_rows = ReviewQueue().list_ready()[:10]
    lib = StrategyIdeaLibrary(ideas_dir)
    ideas = lib.report()
    active_symbols = status.get("symbols", []) or ["BTCUSDT"]
    active_regimes = list((status.get("current_regime") or {}).values()) or ["RANGE", "TREND_UP"]
    llm_ideas = lib.summarize_for_llm(symbols=active_symbols[:4], regimes=active_regimes[:4], limit_per_pair=3)
    return {
        "recent_performance": status.get("risk_caps_status", {}),
        "regime_distribution": status.get("current_regime", {}),
        "top_failure_cases": [status.get("last_decision", {}).get("blocked_reason")],
        "spread_slippage_funding": status.get("last_decision", {}).get("score_components", {}),
        "risk_state": {"safe_pause": status.get("safe_pause"), "reduce_only": status.get("reduce_only")},
        "candidate_registry_summary": candidate_report,
        "startup_restart_recovery": {
            "state": status.get("state"),
            "ws_status": status.get("ws_status", {}),
            "account_sync_health": status.get("account_sync_health", {}),
        },
        "paper_micro_live_outcomes": candidate_report.get("latest", []),
        "review_queue": queue_rows,
        "strategy_idea_library": {
            "summary": {
                "total": ideas.get("total", 0),
                "implemented_plugin_count": len(ideas.get("implemented_plugins", [])),
                "idea_only_count": len(ideas.get("idea_only", [])),
                "proposed_future_count": len(ideas.get("proposed_for_future_implementation", [])),
            },
            "implemented_plugins": ideas.get("implemented_plugins", [])[:10],
            "strict_track_candidates": ideas.get("strict_track_candidates", [])[:10],
            "top_ranked_by_symbol_regime": llm_ideas.get("top_ranked_by_symbol_regime", {}),
            "validation": llm_ideas.get("validation", {}),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--status-file", default="runtime/status.json")
    parser.add_argument("--prompt", default="Diagnose current system and suggest config candidates.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    llm_cfg = cfg.get("llm_research") or cfg.get("llm", {})
    svc = LLMResearchService(llm_cfg)
    ideas_dir = (cfg.get("bootstrap") or {}).get("strategy_idea_library_dir", "strategy_ideas")
    bundle = _compact_research_bundle(args.status_file, ideas_dir=ideas_dir)
    artifact = svc.research(args.prompt, bundle=bundle)
    structured = artifact.get("structured", {})
    warnings = structured.get("warnings") or []
    code_level = any("code" in str(x).lower() for x in warnings) or bool(structured.get("proposed_code_patch"))
    candidate_type = "code" if code_level else ("search-space" if structured.get("search_space_patch") else "config")
    track = "strict" if candidate_type == "code" else "fast"

    candidate_id = f"llm_{artifact['id'][:10]}"
    registry = CandidateRegistry()
    queue = ReviewQueue()
    artifact_root = pathlib.Path("runtime/review_artifacts")
    artifact_root.mkdir(parents=True, exist_ok=True)
    candidate_dir = artifact_root / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "summary.md").write_text(f"# {candidate_id}\n\n{artifact.get('summary','')}\n", encoding="utf-8")
    (candidate_dir / "structured.json").write_text(json.dumps(artifact.get("structured", {}), indent=2), encoding="utf-8")
    (candidate_dir / "validation_report.json").write_text(json.dumps({"llm_only": True, "auto_deploy": False, "budget": artifact.get("budget", {})}, indent=2), encoding="utf-8")
    registry.register(
        candidate_id,
        score=0.0,
        meta={
            "symbol": "MULTI",
            "regime": "MIXED",
            "symbols": ["MULTI"],
            "regimes": ["MIXED"],
            "candidate_type": candidate_type,
            "track": track,
            "summary": artifact["summary"][:500],
            "diagnosis": artifact.get("structured", {}).get("diagnosis", ""),
            "backtest_result": None,
            "oos_result": None,
            "config_patch": artifact.get("structured", {}).get("config_patch") or {},
            "risk_notes": "requires manual validation; LLM output never auto-deploys",
            "provider_used": artifact["provider"],
            "validation_report": {"llm_only": True, "auto_deploy": False, "budget": artifact.get("budget", {})},
            "artifact_bundle": str(candidate_dir),
            "code_change": code_level,
        },
    )
    registry.transition(candidate_id, "config_generated")
    registry.transition(candidate_id, "ready_for_review")
    queue.enqueue(
        {
            "id": candidate_id,
            "type": candidate_type,
            "track": track,
            "symbols": ["MULTI"],
            "regimes": ["MIXED"],
            "strategy_family": "LLMProposal",
            "provider": artifact["provider"],
            "backtest_result": None,
            "oos_result": None,
            "paper_smoke_result": None,
            "risk_notes": "manual strict review required" if track == "strict" else "manual review required",
            "config_patch": artifact.get("structured", {}).get("config_patch") or {},
            "warnings": (artifact.get("structured", {}).get("warnings") or []) + ["LLM-generated idea; deterministic validation required"],
            "recommendation": "hold_for_validation",
            "structured": artifact.get("structured", {}),
            "created_ts": time.time(),
        }
    )

    state_store = EngineStateStore(cfg.get("state", {}).get("engine_state_file", "runtime/engine_state.json"))
    payload = state_store.load()
    history = payload.get("llm_review_history", [])
    history.append({
        "candidate_id": candidate_id,
        "artifact_path": artifact.get("artifact_path"),
        "provider": artifact.get("provider"),
        "structured": artifact.get("structured", {}),
        "budget": artifact.get("budget", {}),
        "ts": time.time(),
    })
    payload["llm_review_history"] = history[-200:]
    state_store.save(payload)
    print(json.dumps({"artifact": artifact, "candidate_id": candidate_id}, indent=2))


if __name__ == "__main__":
    main()
