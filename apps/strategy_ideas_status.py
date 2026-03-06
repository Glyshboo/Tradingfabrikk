from __future__ import annotations

import argparse
import json

from packages.research.strategy_ideas import StrategyIdeaLibrary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ideas-dir", default="strategy_ideas")
    args = parser.parse_args()

    report = StrategyIdeaLibrary(args.ideas_dir).report()
    payload = {
        "ideas_dir": args.ideas_dir,
        "total_seeded": report.get("total", 0),
        "mapped_to_implemented_plugins": len(report.get("implemented_plugins", [])),
        "idea_only": len(report.get("idea_only", [])),
        "partially_implemented": len(report.get("partially_implemented", [])),
        "proposed_for_future_implementation": len(report.get("proposed_for_future_implementation", [])),
        "strict_track_candidates": len(report.get("strict_track_candidates", [])),
        "manifest_valid": (report.get("validation") or {}).get("manifest", {}).get("valid", False),
        "schema_valid": (report.get("validation") or {}).get("valid", False),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
