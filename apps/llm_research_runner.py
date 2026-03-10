from __future__ import annotations

import argparse
import json
import pathlib
import time

from packages.core.config import load_config
from packages.core.state_store import EngineStateStore
from packages.llm.research import LLMResearchService
from packages.research.candidate_bridge import validate_llm_candidate_payload
from packages.research.candidate_registry import CandidateRegistry
from packages.research.strategy_ideas import StrategyIdeaLibrary
from packages.review.review_queue import ReviewQueue


DEFAULT_EDGE_RESEARCH_PROMPT = """You are an advisory-only crypto futures research analyst. Return ONLY strict JSON matching the required schema.

Mission:
- Propose robust, testable NET edge hypotheses for Binance futures.
- Prioritize durable net edge (after fees, slippage, and funding) over raw gross profit.
- Assume overfitting is the #1 risk and design against it.

Hard constraints:
- No auto-live deploy. No order decisions. No execution/risk-engine policy changes.
- Review-gated output only. Fail closed if evidence is weak.
- Propose only hypotheses that can be validated with backtest + OOS + paper/micro-live review.

Output expectations:
- Explain why the edge may exist in real market microstructure/behavior.
- Explicitly separate recommendations into: config tweak, search-space tweak, regime/selector tweak, and strict-track code idea.
- Include concrete failure-mode target, expected market regime, validation plan, and overfit risk controls.
- Keep config/search-space patches minimal, safe, and compatible with existing provider/budget architecture.
- If uncertain, reduce confidence and add warnings.
"""

def _manual_workflow_message(export_path: str = "runtime/llm_exports/paste_to_llm.md") -> str:
    return (
        "[legacy/optional] Internal LLM API research is disabled in config. "
        f"Use the standard manual workflow: open {export_path}, copy/paste into your LLM, "
        "then bring the response back to Codex for implementation."
    )


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
    latest_candidates = candidate_report.get("latest", [])
    return {
        "recent_performance": status.get("risk_caps_status", {}),
        "regime_distribution": status.get("current_regime", {}),
        "market_features": status.get("market_features", {}),
        "top_failure_cases": [status.get("last_decision", {}).get("blocked_reason")],
        "spread_slippage_funding": status.get("last_decision", {}).get("score_components", {}),
        "execution_quality": {
            "latest_order_failures": status.get("latest_order_failures", []),
            "last_decision_reason": status.get("last_decision", {}).get("reason"),
        },
        "risk_state": {"safe_pause": status.get("safe_pause"), "reduce_only": status.get("reduce_only")},
        "candidate_registry_summary": candidate_report,
        "startup_restart_recovery": {
            "state": status.get("state"),
            "ws_status": status.get("ws_status", {}),
            "account_sync_health": status.get("account_sync_health", {}),
        },
        "paper_micro_live_outcomes": candidate_report.get("latest", []),
        "review_feedback_hints": [
            {
                "candidate_id": row.get("id"),
                "state": row.get("state"),
                "track": row.get("track"),
                "type": row.get("type"),
            }
            for row in latest_candidates[:6]
        ],
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


def run_llm_research(
    *,
    config_path: str,
    status_file: str = "runtime/status.json",
    prompt: str = DEFAULT_EDGE_RESEARCH_PROMPT,
    trigger_source: str = "manual",
    trigger_reasons: list[str] | None = None,
    trigger_context: dict | None = None,
) -> dict:
    cfg = load_config(config_path)
    llm_cfg = cfg.get("llm_research") or cfg.get("llm", {})
    if not llm_cfg.get("enabled", False):
        message = _manual_workflow_message()
        result = {"skipped": "llm_research_disabled", "message": message}
        print(message)
        print(json.dumps(result, indent=2))
        return result

    svc = LLMResearchService(llm_cfg)
    ideas_dir = (cfg.get("bootstrap") or {}).get("strategy_idea_library_dir", "strategy_ideas")
    bundle = _compact_research_bundle(status_file, ideas_dir=ideas_dir)
    artifact = svc.research(prompt, bundle=bundle)
    structured = artifact.get("structured", {})
    warnings = structured.get("warnings") or []
    code_level = any("code" in str(x).lower() for x in warnings) or bool(structured.get("proposed_code_patch"))
    candidate_type = "code" if code_level else ("search-space" if structured.get("search_space_patch") else "config")
    track = "strict" if candidate_type == "code" else "fast"
    executable_ok, executable_errors, normalized = validate_llm_candidate_payload(cfg, structured)
    research_fields = {
        "edge_hypothesis": structured.get("edge_hypothesis", ""),
        "failure_mode_target": structured.get("failure_mode_target", ""),
        "expected_market_regime": structured.get("expected_market_regime", ""),
        "validation_plan": structured.get("validation_plan", ""),
        "risk_to_overfit": structured.get("risk_to_overfit", ""),
    }

    candidate_id = f"llm_{artifact['id'][:10]}"
    registry = CandidateRegistry()
    queue = ReviewQueue()
    artifact_root = pathlib.Path("runtime/review_artifacts")
    artifact_root.mkdir(parents=True, exist_ok=True)
    candidate_dir = artifact_root / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "summary.md").write_text(f"# {candidate_id}\n\n{artifact.get('summary','')}\n", encoding="utf-8")
    (candidate_dir / "structured.json").write_text(json.dumps(artifact.get("structured", {}), indent=2), encoding="utf-8")
    (candidate_dir / "validation_report.json").write_text(json.dumps({"llm_only": True, "auto_deploy": False, "budget": artifact.get("budget", {}), "executable_ok": executable_ok, "errors": executable_errors}, indent=2), encoding="utf-8")
    validation_report = {"llm_only": True, "auto_deploy": False, "budget": artifact.get("budget", {}), "executable_ok": executable_ok, "errors": executable_errors}
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
            "edge_hypothesis": research_fields["edge_hypothesis"],
            "failure_mode_target": research_fields["failure_mode_target"],
            "expected_market_regime": research_fields["expected_market_regime"],
            "validation_plan": research_fields["validation_plan"],
            "risk_to_overfit": research_fields["risk_to_overfit"],
            "backtest_result": None,
            "oos_result": None,
            "config_patch": normalized.get("config_patch", {}),
            "strategy_profile_patch": normalized.get("strategy_profile_patch", {}),
            "search_space_patch": normalized.get("search_space_patch", {}),
            "research_fields": research_fields,
            "risk_notes": "requires manual validation; LLM output never auto-deploys",
            "provider_used": artifact["provider"],
            "validation_report": validation_report,
            "artifact_bundle": str(candidate_dir),
            "code_change": code_level,
            "trigger_source": trigger_source,
            "trigger_reasons": trigger_reasons or ["manual"],
            "trigger_context": trigger_context or {},
        },
    )
    registry.transition(candidate_id, "config_generated")
    if executable_ok and track != "strict":
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
                "config_patch": normalized.get("config_patch", {}),
                "search_space_patch": normalized.get("search_space_patch", {}),
                "warnings": (artifact.get("structured", {}).get("warnings") or []) + ["LLM-generated idea; deterministic validation required"],
                "recommendation": "hold_for_validation",
                "structured": artifact.get("structured", {}),
                "created_ts": time.time(),
            }
        )
    else:
        registry.transition(candidate_id, "validation_failed")

    state_store = EngineStateStore(cfg.get("state", {}).get("engine_state_file", "runtime/engine_state.json"))
    payload = state_store.load()
    history = payload.get("llm_review_history", [])
    history.append({
        "candidate_id": candidate_id,
        "artifact_path": artifact.get("artifact_path"),
        "provider": artifact.get("provider"),
        "structured": artifact.get("structured", {}),
        "budget": artifact.get("budget", {}),
        "trigger_source": trigger_source,
        "trigger_reasons": trigger_reasons or ["manual"],
        "trigger_context": trigger_context or {},
        "ts": time.time(),
    })
    payload["llm_review_history"] = history[-200:]
    state_store.save(payload)
    result = {"artifact": artifact, "candidate_id": candidate_id}
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--status-file", default="runtime/status.json")
    parser.add_argument("--prompt", default=DEFAULT_EDGE_RESEARCH_PROMPT)
    args = parser.parse_args()
    run_llm_research(config_path=args.config, status_file=args.status_file, prompt=args.prompt)


if __name__ == "__main__":
    main()
