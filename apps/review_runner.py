from __future__ import annotations

import argparse
import json
import pathlib
import time

from packages.research.candidate_registry import CandidateRegistry
from packages.review.paper_smoke import PaperSmokeWorker
from packages.review.review_queue import ReviewQueue


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified review entrypoint")
    parser.add_argument("--action", choices=["list", "approve_micro_live", "approve_live_full", "reject", "hold", "keep_paper"], default="list")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    queue = ReviewQueue()
    registry = CandidateRegistry()

    if args.action == "list":
        rows = queue.list_ready()
        print(json.dumps({"pending": rows, "count": len(rows)}, indent=2))
        return

    if not args.candidate_id:
        raise SystemExit("--candidate-id is required for non-list actions")

    record = registry.get(args.candidate_id)
    if record is None:
        raise SystemExit(f"candidate not found in registry: {args.candidate_id}")
    if args.action == "approve_micro_live" and record.get("state") != "ready_for_review":
        raise SystemExit("approve_micro_live requires ready_for_review state")
    if args.action == "approve_live_full" and record.get("state") not in {
        "approved_for_micro_live",
        "micro_live_active",
        "micro_live_resumed",
    }:
        raise SystemExit("approve_live_full is only allowed after micro-live state")
    if record.get("type") in {"risk", "execution", "code"} and record.get("track") != "strict":
        raise SystemExit("protected candidate types must remain on strict track")

    if args.action == "hold":
        registry.update_meta(args.candidate_id, meta_patch={"hold_until_ts": time.time() + 15 * 60, "keep_paper": False, "runtime_hold": True})
    if args.action == "keep_paper":
        registry.update_meta(args.candidate_id, meta_patch={"keep_paper": True, "hold_until_ts": None, "runtime_hold": False})
    result = queue.apply_action(args.candidate_id, args.action, args.note)
    mapping = {
        "approve_micro_live": "approved_for_micro_live",
        "approve_live_full": "approved_for_live_full",
        "hold": "paper_candidate_paused",
        "keep_paper": "paper_candidate_active",
        "reject": "rejected",
    }
    registry.transition(args.candidate_id, mapping[args.action])
    worker = PaperSmokeWorker(registry, {"symbols": record.get("symbols") or [record.get("meta", {}).get("symbol", "MULTI")]})
    smoke_actions = worker.process()

    out = pathlib.Path("runtime/reviews")
    out.mkdir(parents=True, exist_ok=True)
    review_file = out / f"{args.candidate_id}_{args.action}.json"
    review_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"result": result, "review_file": str(review_file), "paper_smoke_actions": smoke_actions}, indent=2))


if __name__ == "__main__":
    main()
