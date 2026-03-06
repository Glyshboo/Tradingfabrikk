from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass


STATES = ["candidate", "backtest_pass", "paper_pass", "ready_for_review", "live_approved"]
STATE_ORDER = {name: idx for idx, name in enumerate(STATES)}


@dataclass
class CandidateRecord:
    candidate_id: str
    state: str
    score: float
    meta: dict


class CandidateRegistry:
    def __init__(self, path: str = "runtime/candidates_registry.json") -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"candidates": {}}, indent=2), encoding="utf-8")

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register(self, candidate_id: str, score: float, meta: dict) -> None:
        data = self._load()
        row = data["candidates"].get(candidate_id, {})
        row.update({
            "state": "candidate",
            "score": score,
            "meta": meta,
            "updated_ts": time.time(),
            "history": row.get("history", []) + [{"state": "candidate", "ts": time.time()}],
        })
        data["candidates"][candidate_id] = row
        self._save(data)

    def transition(self, candidate_id: str, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"invalid state {state}")
        data = self._load()
        if candidate_id in data["candidates"]:
            current_state = data["candidates"][candidate_id].get("state", "candidate")
            if STATE_ORDER[state] < STATE_ORDER.get(current_state, 0):
                raise ValueError(f"invalid backward transition {current_state} -> {state}")
            data["candidates"][candidate_id]["state"] = state
            data["candidates"][candidate_id]["updated_ts"] = time.time()
            history = data["candidates"][candidate_id].get("history", [])
            history.append({"state": state, "ts": time.time()})
            data["candidates"][candidate_id]["history"] = history
            self._save(data)

    def report(self) -> dict:
        data = self._load()
        counts = {s: 0 for s in STATES}
        for row in data["candidates"].values():
            if row["state"] in counts:
                counts[row["state"]] += 1
        newest = sorted(
            [{"id": cid, "state": row.get("state"), "score": row.get("score"), "updated_ts": row.get("updated_ts")} for cid, row in data["candidates"].items()],
            key=lambda x: x.get("updated_ts") or 0,
            reverse=True,
        )[:10]
        return {"counts": counts, "total": len(data["candidates"]), "latest": newest}
