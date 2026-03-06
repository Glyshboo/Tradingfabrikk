from __future__ import annotations

import argparse
import json

from packages.core.config import load_config
from packages.llm.research import LLMResearchService
from packages.research.candidate_registry import CandidateRegistry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--prompt", default="Diagnose current system and suggest config candidates.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    svc = LLMResearchService(cfg.get("llm", {}))
    artifact = svc.research(args.prompt)

    candidate_id = f"llm_{artifact['id'][:10]}"
    registry = CandidateRegistry()
    registry.register(
        candidate_id,
        score=0.0,
        meta={
            "symbol": "MULTI",
            "regime": "MIXED",
            "track": "strict",
            "summary": artifact["summary"][:500],
            "backtest_result": None,
            "config_patch": None,
            "risk_notes": "requires manual validation; LLM output never auto-deploys",
            "provider_used": artifact["provider"],
            "code_change": True,
        },
    )
    registry.transition(candidate_id, "ready_for_review")
    print(json.dumps({"artifact": artifact, "candidate_id": candidate_id}, indent=2))


if __name__ == "__main__":
    main()
