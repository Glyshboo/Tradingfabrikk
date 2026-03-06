from __future__ import annotations

import argparse
import json
import pathlib
import time

from packages.core.config import load_config
from packages.llm.research import LLMResearchService
from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ReviewQueue


def _compact_research_bundle(status_file: str) -> dict:
    status_path = pathlib.Path(status_file)
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    candidate_report = CandidateRegistry().report()
    queue_rows = ReviewQueue().list_ready()[:10]
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
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--status-file", default="runtime/status.json")
    parser.add_argument("--prompt", default="Diagnose current system and suggest config candidates.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    svc = LLMResearchService(cfg.get("llm", {}))
    bundle = _compact_research_bundle(args.status_file)
    artifact = svc.research(args.prompt, bundle=bundle)

    candidate_id = f"llm_{artifact['id'][:10]}"
    registry = CandidateRegistry()
    queue = ReviewQueue()
    registry.register(
        candidate_id,
        score=0.0,
        meta={
            "symbol": "MULTI",
            "regime": "MIXED",
            "symbols": ["MULTI"],
            "regimes": ["MIXED"],
            "candidate_type": "code",
            "track": "strict",
            "summary": artifact["summary"][:500],
            "backtest_result": None,
            "oos_result": None,
            "config_patch": None,
            "risk_notes": "requires manual validation; LLM output never auto-deploys",
            "provider_used": artifact["provider"],
            "validation_report": {"llm_only": True, "auto_deploy": False},
            "code_change": True,
        },
    )
    registry.transition(candidate_id, "config_generated")
    registry.transition(candidate_id, "ready_for_review")
    queue.enqueue(
        {
            "id": candidate_id,
            "type": "code",
            "track": "strict",
            "symbols": ["MULTI"],
            "regimes": ["MIXED"],
            "strategy_family": "LLMProposal",
            "provider": artifact["provider"],
            "backtest_result": None,
            "oos_result": None,
            "paper_smoke_result": None,
            "risk_notes": "manual strict review required",
            "config_patch": None,
            "warnings": ["LLM-generated idea; deterministic validation required"],
            "recommendation": "hold_for_validation",
            "created_ts": time.time(),
        }
    )
    print(json.dumps({"artifact": artifact, "candidate_id": candidate_id}, indent=2))


if __name__ == "__main__":
    main()
