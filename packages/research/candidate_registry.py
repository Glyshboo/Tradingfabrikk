from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass


STATES = [
    "candidate",
    "backtest_pass",
    "oos_pass",
    "paper_pass",
    "ready_for_review",
    "paper_hold",
    "micro_live",
    "live_approved",
    "rejected",
]
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
        now = time.time()
        row.update(
            {
                "state": "candidate",
                "score": score,
                "meta": meta,
                "track": meta.get("track", "fast"),
                "artifacts": {
                    "summary": meta.get("summary"),
                    "backtest_result": meta.get("backtest_result"),
                    "paper_smoke_result": meta.get("paper_smoke_result"),
                    "config_patch": meta.get("config_patch"),
                    "risk_notes": meta.get("risk_notes"),
                    "provider_used": meta.get("provider_used"),
                    "code_change": bool(meta.get("code_change", False)),
                },
                "updated_ts": now,
                "history": row.get("history", []) + [{"state": "candidate", "ts": now}],
            }
        )
        data["candidates"][candidate_id] = row
        self._save(data)

    def transition(self, candidate_id: str, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"invalid state {state}")
        data = self._load()
        if candidate_id in data["candidates"]:
            current_state = data["candidates"][candidate_id].get("state", "candidate")
            if state in {"rejected", "paper_hold", "micro_live", "live_approved"}:
                pass
            elif STATE_ORDER[state] < STATE_ORDER.get(current_state, 0):
                raise ValueError(f"invalid backward transition {current_state} -> {state}")
            data["candidates"][candidate_id]["state"] = state
            data["candidates"][candidate_id]["updated_ts"] = time.time()
            history = data["candidates"][candidate_id].get("history", [])
            history.append({"state": state, "ts": time.time()})
            data["candidates"][candidate_id]["history"] = history
            self._save(data)

    def list_ready_for_review(self) -> list[dict]:
        data = self._load()
        return [
            {"id": cid, **row}
            for cid, row in data["candidates"].items()
            if row.get("state") == "ready_for_review"
        ]

    def report(self) -> dict:
        data = self._load()
        counts = {s: 0 for s in STATES}
        for row in data["candidates"].values():
            if row["state"] in counts:
                counts[row["state"]] += 1
        newest = sorted(
            [{"id": cid, "state": row.get("state"), "score": row.get("score"), "updated_ts": row.get("updated_ts"), "track": row.get("track", "fast")} for cid, row in data["candidates"].items()],
            key=lambda x: x.get("updated_ts") or 0,
            reverse=True,
        )[:10]
        return {"counts": counts, "total": len(data["candidates"]), "latest": newest}
