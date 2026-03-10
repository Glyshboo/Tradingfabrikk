from __future__ import annotations

import argparse
import json
import pathlib

from apps.llm_research_runner import run_llm_research
from apps.research_runner import run_research
from packages.core.config import load_config
from packages.research.auto_orchestrator import AutoResearchOrchestrator
from packages.research.export_refresh_service import ExportRefreshService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--status-file", default="runtime/status.json")
    parser.add_argument("--state-file", default="runtime/auto_research_state.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    auto_cfg = cfg.get("auto_research") or {}

    def deterministic_runner(reasons: list[str], context: dict) -> dict:
        return run_research(
            config_path=args.config,
            trigger_source="auto_orchestrator",
            trigger_reasons=reasons,
            trigger_context={
                "reason_details": context.get("decision_details", {}),
                "mode": context.get("mode"),
            },
        )

    def llm_runner(reasons: list[str], context: dict) -> dict:
        if not auto_cfg.get("llm", {}).get("enabled", False):
            return {"skipped": "llm_disabled"}
        return run_llm_research(
            config_path=args.config,
            status_file=args.status_file,
            trigger_source="auto_orchestrator",
            trigger_reasons=reasons,
            trigger_context={
                "reason_details": context.get("decision_details", {}),
                "mode": context.get("mode"),
            },
        )

    orchestrator = AutoResearchOrchestrator(
        cfg={
            "mode": cfg.get("mode"),
            "risk": cfg.get("risk", {}),
            "triggers": auto_cfg.get("triggers", {}),
            "llm": auto_cfg.get("llm", {}),
        },
        status_file=args.status_file,
        engine_state_file=cfg.get("state", {}).get("engine_state_file", "runtime/engine_state.json"),
        state_file=args.state_file,
        deterministic_runner=deterministic_runner,
        llm_runner=llm_runner,
    )
    report = orchestrator.run_once()
    if report.get("triggered"):
        report["export_refresh"] = ExportRefreshService.from_config(cfg).refresh_exports(
            trigger="auto_research_runner",
            context={"reasons": report.get("reasons", [])},
        )
    artifact = pathlib.Path(auto_cfg.get("artifact_file", "runtime/auto_research_last_report.json"))
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
