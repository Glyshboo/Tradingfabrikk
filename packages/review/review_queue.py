from __future__ import annotations

import json
import pathlib
import time

ALLOWED_ACTIONS = {"approve", "reject", "hold", "micro_live"}


class ReviewQueue:
    def __init__(self, path: str = "runtime/review_queue.json") -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"queue": [], "history": []}, indent=2), encoding="utf-8")

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def enqueue(self, candidate: dict) -> None:
        payload = self._load()
        if any(x.get("id") == candidate.get("id") for x in payload["queue"]):
            return
        payload["queue"].append(candidate)
        self._save(payload)

    def list_ready(self) -> list[dict]:
        return self._load()["queue"]

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
            "ts": time.time(),
        }
        payload["queue"] = rest
        payload["history"].append(result)
        self._save(payload)
        return result
