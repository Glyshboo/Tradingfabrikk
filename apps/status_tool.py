from __future__ import annotations

import argparse
import json
import pathlib

from packages.research.candidate_registry import CandidateRegistry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", default="runtime/status.json")
    args = parser.parse_args()

    p = pathlib.Path(args.status_file)
    if not p.exists():
        print("No status file found")
        return
    status = json.loads(p.read_text(encoding="utf-8"))
    last_decision = status.get("last_decision") or {}
    decision_view = {
        "symbol": last_decision.get("symbol"),
        "regime": last_decision.get("regime"),
        "eligible_strategies": last_decision.get("eligible_strategies", []),
        "score_breakdown": last_decision.get("score_breakdown", {}),
        "selected_candidate": last_decision.get("selected_candidate"),
        "selected_side": last_decision.get("selected_side"),
        "side": last_decision.get("side"),
        "qty": last_decision.get("qty"),
        "score_components": last_decision.get("score_components", {}),
        "blocked_reason": last_decision.get("blocked_reason"),
        "caps_status": last_decision.get("caps_status", {}),
    }

    candidate_report = CandidateRegistry().report()

    view = {
        "mode": status.get("mode"),
        "state": status.get("state"),
        "symbols": status.get("symbols", []),
        "recovery_state": status.get("recovery_state", {}),
        "open_positions": status.get("open_positions", {}),
        "last_decision": decision_view,
        "ws_status": status.get("ws_status", {}),
        "account_sync_health": status.get("account_sync_health", {}),
        "current_regime": status.get("current_regime", {}),
        "market_features": status.get("market_features", {}),
        "risk_caps_status": status.get("risk_caps_status", {}),
        "safe_pause": status.get("safe_pause"),
        "reduce_only": status.get("reduce_only"),
        "candidate_registry": candidate_report,
        "review_queue_size": status.get("review_queue_size"),
        "llm_status": status.get("llm_status", {}),
        "micro_live": status.get("micro_live", {}),
        "paper_candidate": status.get("paper_candidate", {}),
        "live_full": status.get("live_full", {}),
        "runtime_overlays": status.get("runtime_overlays", {}),
        "bootstrap": status.get("bootstrap", {}),
        "last_review_result_location": status.get("last_review_result_location"),
        "ts": status.get("ts"),
    }
    print(json.dumps(view, indent=2))


if __name__ == "__main__":
    main()
