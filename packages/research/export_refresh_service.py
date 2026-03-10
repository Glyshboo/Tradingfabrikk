from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from packages.research.llm_export_bundle import ResearchBundleExporter
from packages.telemetry.logging_utils import log_event


class ExportRefreshService:
    def __init__(
        self,
        cfg: dict | None = None,
        *,
        now_fn: Callable[[], float] | None = None,
        exporter_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.cfg = cfg or {}
        self.now_fn = now_fn or time.time
        self.output_dir = Path(self.cfg.get("output_dir", "runtime/llm_exports"))
        self.state_file = Path(self.cfg.get("state_file", str(self.output_dir / "refresh_state.json")))
        self.exporter_factory = exporter_factory or self._build_exporter
        self._state = self._load_state()

    @classmethod
    def from_config(cls, cfg: dict) -> "ExportRefreshService":
        exports_cfg = cfg.get("exports") or {}
        return cls(
            {
                "enabled": bool(exports_cfg.get("enabled", True)),
                "output_dir": exports_cfg.get("output_dir", "runtime/llm_exports"),
                "state_file": exports_cfg.get("state_file", "runtime/llm_exports/refresh_state.json"),
                "status_file": exports_cfg.get("status_file") or cfg.get("telemetry", {}).get("status_file", "runtime/status.json"),
                "registry_file": exports_cfg.get("registry_file") or cfg.get("review", {}).get("candidate_registry_file", "runtime/candidates_registry.json"),
                "engine_state_file": exports_cfg.get("engine_state_file") or cfg.get("state", {}).get("engine_state_file", "runtime/engine_state.json"),
                "review_queue_file": exports_cfg.get("review_queue_file") or cfg.get("review", {}).get("queue_file", "runtime/review_queue.json"),
                "ranking_file": exports_cfg.get("ranking_file", "configs/candidates/ranking.json"),
                "refresh_on_research": bool(exports_cfg.get("refresh_on_research", True)),
                "refresh_on_auto_research": bool(exports_cfg.get("refresh_on_auto_research", True)),
                "refresh_on_candidate_change": bool(exports_cfg.get("refresh_on_candidate_change", True)),
                "refresh_on_challenger_eval": bool(exports_cfg.get("refresh_on_challenger_eval", True)),
                "refresh_on_schedule": bool(exports_cfg.get("refresh_on_schedule", False)),
                "min_refresh_interval_sec": float(exports_cfg.get("min_refresh_interval_sec", 900)),
                "schedule_interval_sec": float(exports_cfg.get("schedule_interval_sec", 1800)),
            }
        )


    def _build_exporter(self) -> ResearchBundleExporter:
        return ResearchBundleExporter(
            status_file=str(self.cfg.get("status_file", "runtime/status.json")),
            registry_file=str(self.cfg.get("registry_file", "runtime/candidates_registry.json")),
            engine_state_file=str(self.cfg.get("engine_state_file", "runtime/engine_state.json")),
            review_queue_file=str(self.cfg.get("review_queue_file", "runtime/review_queue.json")),
            ranking_file=str(self.cfg.get("ranking_file", "configs/candidates/ranking.json")),
            output_dir=str(self.output_dir),
        )

    def _load_state(self) -> dict:
        if not self.state_file.exists():
            return {"last_refresh_ts": 0.0, "last_schedule_probe_ts": 0.0}
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {"last_refresh_ts": 0.0, "last_schedule_probe_ts": 0.0}

    def _persist_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _trigger_enabled(self, trigger: str) -> bool:
        mapping = {
            "research_runner": "refresh_on_research",
            "auto_research_runner": "refresh_on_auto_research",
            "candidate_change": "refresh_on_candidate_change",
            "challenger_eval": "refresh_on_challenger_eval",
            "engine_schedule": "refresh_on_schedule",
        }
        flag = mapping.get(trigger)
        return bool(self.cfg.get(flag, False)) if flag else True

    def refresh_exports(self, *, trigger: str, context: dict | None = None, force: bool = False) -> dict:
        context = context or {}
        now = float(self.now_fn())
        if not self.cfg.get("enabled", True):
            return {"refreshed": False, "skipped": "disabled", "trigger": trigger}
        if not self._trigger_enabled(trigger):
            return {"refreshed": False, "skipped": "trigger_disabled", "trigger": trigger}

        min_interval = max(0.0, float(self.cfg.get("min_refresh_interval_sec", 900)))
        last_refresh = float(self._state.get("last_refresh_ts", 0.0) or 0.0)
        if not force and (now - last_refresh) < min_interval:
            return {
                "refreshed": False,
                "skipped": "cooldown",
                "trigger": trigger,
                "next_allowed_in_sec": max(0.0, min_interval - (now - last_refresh)),
            }

        try:
            exporter = self.exporter_factory()
            report = exporter.export()
        except Exception as exc:
            log_event("exports_refresh_failed", {"trigger": trigger, "error": str(exc), "context": context})
            return {"refreshed": False, "failed": True, "trigger": trigger, "error": str(exc)}

        self._state["last_refresh_ts"] = now
        self._persist_state()
        log_event("exports_refreshed", {"trigger": trigger, "context": context, "output_dir": report.get("output_dir")})
        return {"refreshed": True, "trigger": trigger, "report": report}

    def maybe_refresh_on_schedule(self, *, context: dict | None = None) -> dict:
        now = float(self.now_fn())
        interval = max(0.0, float(self.cfg.get("schedule_interval_sec", 1800)))
        last_probe = float(self._state.get("last_schedule_probe_ts", 0.0) or 0.0)
        self._state["last_schedule_probe_ts"] = now
        self._persist_state()
        if interval > 0 and (now - last_probe) < interval:
            return {"refreshed": False, "skipped": "schedule_interval", "trigger": "engine_schedule"}
        return self.refresh_exports(trigger="engine_schedule", context=context or {})
