from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any


STATES = ["candidate", "backtest_pass", "paper_pass", "ready_for_review", "live_approved"]
_ALLOWED_TRANSITIONS = {
    "candidate": {"backtest_pass"},
    "backtest_pass": {"paper_pass", "candidate"},
    "paper_pass": {"ready_for_review", "backtest_pass"},
    "ready_for_review": {"live_approved", "paper_pass"},
    "live_approved": set(),
}


@dataclass
class CandidateRecord:
    candidate_id: str
    state: str
    score: float
    meta: dict[str, Any]


class CandidateRegistry:
    def __init__(self, path: str = "runtime/candidates_registry.json") -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"candidates": {}}, indent=2), encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register(self, candidate_id: str, score: float, meta: dict[str, Any]) -> None:
        data = self._load()
        data["candidates"][candidate_id] = {
            "state": "candidate",
            "score": float(score),
            "meta": dict(meta),
            "paper_eval": None,
        }
        self._save(data)

    def transition(self, candidate_id: str, state: str, strict: bool = True) -> None:
        if state not in STATES:
            raise ValueError(f"invalid state {state}")
        data = self._load()
        row = data["candidates"].get(candidate_id)
        if not row:
            raise KeyError(f"unknown candidate {candidate_id}")

        current = row.get("state", "candidate")
        if strict and state != current and state not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid transition {current} -> {state}")

        row["state"] = state
        self._save(data)

    def store_paper_evaluation(
        self,
        candidate_id: str,
        passed: bool,
        pnl: float,
        max_drawdown: float,
        notes: str = "",
    ) -> None:
        data = self._load()
        row = data["candidates"].get(candidate_id)
        if not row:
            raise KeyError(f"unknown candidate {candidate_id}")

        row["paper_eval"] = {
            "passed": bool(passed),
            "pnl": float(pnl),
            "max_drawdown": float(max_drawdown),
            "notes": notes,
        }
        if passed and row.get("state") == "backtest_pass":
            row["state"] = "paper_pass"
        self._save(data)

    def report(self) -> dict[str, Any]:
        data = self._load()
        counts = {s: 0 for s in STATES}
        paper_passed = 0
        for row in data["candidates"].values():
            state = row.get("state")
            if state in counts:
                counts[state] += 1
            if (row.get("paper_eval") or {}).get("passed"):
                paper_passed += 1
        return {"counts": counts, "total": len(data["candidates"]), "paper_passed": paper_passed}

    def get(self, candidate_id: str) -> CandidateRecord:
        data = self._load()
        row = data["candidates"].get(candidate_id)
        if not row:
            raise KeyError(f"unknown candidate {candidate_id}")
        return CandidateRecord(
            candidate_id=candidate_id,
            state=row.get("state", "candidate"),
            score=float(row.get("score", 0.0)),
            meta=dict(row.get("meta", {})),
        )
