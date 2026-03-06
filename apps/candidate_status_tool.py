from __future__ import annotations

import argparse
import json

from packages.research.candidate_registry import CandidateRegistry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="runtime/candidates_registry.json")
    parser.add_argument("--transition-id", default="")
    parser.add_argument("--transition-state", default="")
    parser.add_argument("--paper-eval-id", default="")
    parser.add_argument("--paper-eval-passed", choices=["true", "false"], default="")
    parser.add_argument("--paper-eval-pnl", type=float, default=0.0)
    parser.add_argument("--paper-eval-max-dd", type=float, default=0.0)
    parser.add_argument("--paper-eval-notes", default="")
    args = parser.parse_args()

    reg = CandidateRegistry(path=args.registry)

    if args.transition_id and args.transition_state:
        reg.transition(args.transition_id, args.transition_state)

    if args.paper_eval_id and args.paper_eval_passed:
        reg.store_paper_evaluation(
            candidate_id=args.paper_eval_id,
            passed=args.paper_eval_passed == "true",
            pnl=args.paper_eval_pnl,
            max_drawdown=args.paper_eval_max_dd,
            notes=args.paper_eval_notes,
        )

    print(json.dumps(reg.report(), indent=2))


if __name__ == "__main__":
    main()
