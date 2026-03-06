from __future__ import annotations

import argparse
import json

from packages.research.candidate_registry import CandidateRegistry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="runtime/candidates_registry.json")
    args = parser.parse_args()

    reg = CandidateRegistry(path=args.registry)
    print(json.dumps(reg.report(), indent=2))


if __name__ == "__main__":
    main()
