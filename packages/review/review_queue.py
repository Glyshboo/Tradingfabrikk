from __future__ import annotations

import json
import pathlib
import time
from json import JSONDecodeError

from packages.telemetry.logging_utils import log_event

ALLOWED_ACTIONS = {"approve_micro_live", "approve_live_full", "reject", "hold", "keep_paper"}


class ReviewQueue:
    def __init__(self, path: str = "runtime/review_queue.json") -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"queue": [], "history": []}, indent=2), encoding="utf-8")

    def _default_payload(self) -> dict:
        return {"queue": [], "history": []}

    def _load(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except JSONDecodeError:
            log_event("runtime_json_invalid", {"file": str(self.path), "fallback": "review_queue_default"})
            payload = self._default_payload()
            self._save(payload)
            return payload
        except OSError as exc:
            log_event("runtime_json_read_error", {"file": str(self.path), "error": str(exc), "fallback": "review_queue_default"})
            payload = self._default_payload()
            self._save(payload)
            return payload
        if not isinstance(payload, dict):
            log_event("runtime_json_invalid", {"file": str(self.path), "fallback": "review_queue_default"})
            payload = self._default_payload()
            self._save(payload)
            return payload
        if not isinstance(payload.get("queue"), list):
            payload["queue"] = []
        if not isinstance(payload.get("history"), list):
            payload["history"] = []
        return payload

    def _save(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def enqueue(self, candidate: dict) -> None:
        payload = self._load()
        if any(x.get("id") == candidate.get("id") for x in payload["queue"]):
            return
        payload["queue"].append(candidate)
        self._save(payload)

    def list_ready(self) -> list[dict]:
        rows = self._load()["queue"]
        return sorted(rows, key=lambda r: r.get("created_ts", 0), reverse=True)

    def apply_action(self, candidate_id: str, action: str, note: str = "") -> dict:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported action: {action}")
        payload = self._load()
        found = None
        rest = []
        for row in payload["queue"]:
            if row.get("id") == candidate_id:
                found = row
            else:
                rest.append(row)
        if found is None:
            raise ValueError(f"candidate not in queue: {candidate_id}")
        result = {
            "id": candidate_id,
            "action": action,
            "note": note,
            "track": found.get("track", "fast"),
            "type": found.get("type", "config"),
            "ts": time.time(),
        }
        payload["queue"] = rest
        payload["history"].append(result)
        self._save(payload)
        return result
