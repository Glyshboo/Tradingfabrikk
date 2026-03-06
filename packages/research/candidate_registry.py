from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass


STATES = ["candidate", "backtest_pass", "paper_pass", "ready_for_review", "live_approved"]


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
        data["candidates"][candidate_id] = {"state": "candidate", "score": score, "meta": meta}
        self._save(data)

    def transition(self, candidate_id: str, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"invalid state {state}")
        data = self._load()
        if candidate_id in data["candidates"]:
            data["candidates"][candidate_id]["state"] = state
            self._save(data)

    def report(self) -> dict:
        data = self._load()
        counts = {s: 0 for s in STATES}
        for row in data["candidates"].values():
            if row["state"] in counts:
                counts[row["state"]] += 1
        return {"counts": counts, "total": len(data["candidates"])}
