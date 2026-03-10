from __future__ import annotations

import argparse
import json

from packages.core.config import load_config
from packages.research.llm_export_bundle import ResearchBundleExporter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--status-file", default="")
    parser.add_argument("--registry-file", default="")
    parser.add_argument("--engine-state-file", default="")
    parser.add_argument("--review-queue-file", default="")
    parser.add_argument("--ranking-file", default="configs/candidates/ranking.json")
    parser.add_argument("--output-dir", default="runtime/llm_exports")
    args = parser.parse_args()

    cfg = load_config(args.config)
    exporter = ResearchBundleExporter(
        status_file=args.status_file or cfg.get("telemetry", {}).get("status_file", "runtime/status.json"),
        registry_file=args.registry_file or cfg.get("review", {}).get("candidate_registry_file", "runtime/candidates_registry.json"),
        engine_state_file=args.engine_state_file or cfg.get("state", {}).get("engine_state_file", "runtime/engine_state.json"),
        review_queue_file=args.review_queue_file or cfg.get("review", {}).get("queue_file", "runtime/review_queue.json"),
        ranking_file=args.ranking_file,
        output_dir=args.output_dir,
    )
    report = exporter.export()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
