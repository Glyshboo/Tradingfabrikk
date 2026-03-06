from __future__ import annotations

import argparse
import json
import pathlib

from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ReviewQueue


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified review entrypoint")
    parser.add_argument("--action", choices=["list", "approve", "reject", "hold", "micro_live"], default="list")
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

    result = queue.apply_action(args.candidate_id, args.action, args.note)
    mapping = {
        "approve": "live_approved",
        "micro_live": "micro_live",
        "hold": "paper_hold",
        "reject": "rejected",
    }
    registry.transition(args.candidate_id, mapping[args.action])

    out = pathlib.Path("runtime/reviews")
    out.mkdir(parents=True, exist_ok=True)
    review_file = out / f"{args.candidate_id}_{args.action}.json"
    review_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"result": result, "review_file": str(review_file)}, indent=2))


if __name__ == "__main__":
    main()
