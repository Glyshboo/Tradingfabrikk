from __future__ import annotations

import json
import pathlib
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class SessionInfo:
    session_id: str
    startup_ts: float
    previous_shutdown_ts: float | None
    downtime_sec: float


class EngineStateStore:
    def __init__(self, path: str = "runtime/engine_state.json") -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps(self._default_payload(), indent=2), encoding="utf-8")

    def _default_payload(self) -> dict[str, Any]:
        return {
            "sessions": [],
            "last_shutdown_ts": None,
            "startup_shutdown_timestamps": [],
            "engine_state": "recovering",
            "position_manager_state": {},
            "risk_state": {},
            "symbol_profiles": {},
            "llm_review_history": [],
            "strategy_performance_history": [],
            "paper_trade_history": [],
            "live_trade_history": [],
            "performance_memory_state": {},
            "review_queue": [],
            "candidate_registry_snapshot": {},
        }

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register_startup(self) -> SessionInfo:
        payload = self.load()
        now = time.time()
        previous_shutdown = payload.get("last_shutdown_ts")
        downtime = max(0.0, now - float(previous_shutdown)) if previous_shutdown else 0.0
        session = SessionInfo(
            session_id=str(uuid.uuid4()),
            startup_ts=now,
            previous_shutdown_ts=previous_shutdown,
            downtime_sec=downtime,
        )
        payload["sessions"].append({
            "session_id": session.session_id,
            "startup_ts": now,
            "previous_shutdown_ts": previous_shutdown,
            "downtime_sec": downtime,
        })
        payload["startup_shutdown_timestamps"].append({"startup_ts": now})
        payload["engine_state"] = "recovering"
        self.save(payload)
        return session

    def register_shutdown(self) -> None:
        payload = self.load()
        now = time.time()
        payload["last_shutdown_ts"] = now
        payload["startup_shutdown_timestamps"].append({"shutdown_ts": now})
        self.save(payload)
