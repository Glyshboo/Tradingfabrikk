from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass


STATES = [
    "idea_proposed",
    "config_generated",
    "validation_failed",
    "backtest_pass",
    "paper_smoke_running",
    "paper_smoke_pass",
    "challenger_active",
    "challenger_evaluated",
    "paper_candidate_active",
    "paper_candidate_paused",
    "paper_candidate_winning",
    "paper_candidate_fading",
    "edge_decay",
    "needs_revalidation",
    "paper_candidate_pass",
    "paper_candidate_fail",
    "ready_for_review",
    "approved_for_micro_live",
    "micro_live_active",
    "micro_live_paused",
    "micro_live_recovering",
    "micro_live_resumed",
    "approved_for_live_full",
    "live_full_active",
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
                "state": "idea_proposed",
                "score": score,
                "meta": meta,
                "type": meta.get("candidate_type", "config"),
                "candidate_kind": meta.get("candidate_kind", "config_tweak"),
                "track": meta.get("track", "fast"),
                "provider": meta.get("provider_used", "unknown"),
                "strategy_family": meta.get("strategy_family"),
                "symbols": meta.get("symbols") or ([meta["symbol"]] if meta.get("symbol") else []),
                "regimes": meta.get("regimes") or ([meta["regime"]] if meta.get("regime") else []),
                "artifacts": {
                    "summary": meta.get("summary"),
                    "backtest_result": meta.get("backtest_result"),
                    "oos_result": meta.get("oos_result"),
                    "paper_smoke_result": meta.get("paper_smoke_result"),
                    "config_patch": meta.get("config_patch"),
                    "strategy_profile_patch": meta.get("strategy_profile_patch"),
                    "search_space_patch": meta.get("search_space_patch"),
                    "research_fields": meta.get("research_fields", {}),
                    "code_patch_summary": meta.get("code_patch_summary"),
                    "risk_notes": meta.get("risk_notes"),
                    "provider_used": meta.get("provider_used"),
                    "validation_report": meta.get("validation_report"),
                    "warnings": meta.get("warnings", []),
                    "recommendation": meta.get("recommendation"),
                    "artifact_bundle": meta.get("artifact_bundle"),
                    "code_change": bool(meta.get("code_change", False)),
                    "strategy_composition": meta.get("strategy_composition", {}),
                },
                "updated_ts": now,
                "history": row.get("history", []) + [{"state": "idea_proposed", "ts": now}],
            }
        )
        data["candidates"][candidate_id] = row
        self._save(data)

    def transition(self, candidate_id: str, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"invalid state {state}")
        data = self._load()
        if candidate_id in data["candidates"]:
            current_state = data["candidates"][candidate_id].get("state", "idea_proposed")
            if state in {
                "rejected",
                "validation_failed",
                "micro_live_paused",
                "paper_candidate_active",
                "paper_candidate_paused",
                "paper_candidate_pass",
                "paper_candidate_fail",
                "challenger_active",
                "challenger_evaluated",
                "paper_candidate_winning",
                "paper_candidate_fading",
                "edge_decay",
                "needs_revalidation",
            }:
                pass
            elif STATE_ORDER[state] < STATE_ORDER.get(current_state, 0):
                raise ValueError(f"invalid backward transition {current_state} -> {state}")
            data["candidates"][candidate_id]["state"] = state
            data["candidates"][candidate_id]["updated_ts"] = time.time()
            history = data["candidates"][candidate_id].get("history", [])
            history.append({"state": state, "ts": time.time()})
            data["candidates"][candidate_id]["history"] = history
            self._save(data)

    def ensure_review_queued(self, review_queue, candidate_id: str, reason: str) -> None:
        row = self.get(candidate_id)
        if row is None:
            return
        review_queue.enqueue(
            {
                "id": candidate_id,
                "type": row.get("type", "config"),
                "track": row.get("track", "fast"),
                "symbols": row.get("symbols") or row.get("meta", {}).get("symbols") or [],
                "regimes": row.get("regimes") or row.get("meta", {}).get("regimes") or [],
                "strategy_family": row.get("strategy_family") or row.get("meta", {}).get("strategy_family"),
                "provider": row.get("provider", "unknown"),
                "backtest_result": row.get("artifacts", {}).get("backtest_result"),
                "oos_result": row.get("artifacts", {}).get("oos_result"),
                "paper_smoke_result": row.get("artifacts", {}).get("paper_smoke_result"),
                "paper_challenger_result": row.get("artifacts", {}).get("paper_challenger_result"),
                "recommendation": row.get("artifacts", {}).get("recommendation", "manual_review"),
                "created_ts": time.time(),
                "reason": reason,
            }
        )

    def list_by_state(self, states: list[str]) -> list[dict]:
        data = self._load()
        allowed = set(states)
        rows = []
        for cid, row in data["candidates"].items():
            if row.get("state") in allowed:
                rows.append({"id": cid, **row})
        return sorted(rows, key=lambda r: r.get("updated_ts", 0), reverse=True)

    def update_meta(self, candidate_id: str, meta_patch: dict | None = None, artifacts_patch: dict | None = None) -> None:
        data = self._load()
        row = data["candidates"].get(candidate_id)
        if row is None:
            return
        if meta_patch:
            meta = row.get("meta", {})
            meta.update(meta_patch)
            row["meta"] = meta
        if artifacts_patch:
            artifacts = row.get("artifacts", {})
            artifacts.update(artifacts_patch)
            row["artifacts"] = artifacts
        row["updated_ts"] = time.time()
        data["candidates"][candidate_id] = row
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
            [{
                "id": cid,
                "state": row.get("state"),
                "score": row.get("score"),
                "updated_ts": row.get("updated_ts"),
                "track": row.get("track", "fast"),
                "type": row.get("type", "config"),
                "provider": row.get("provider", "unknown"),
                "lifecycle_reason": row.get("meta", {}).get("lifecycle_reason", ""),
            } for cid, row in data["candidates"].items()],
            key=lambda x: x.get("updated_ts") or 0,
            reverse=True,
        )[:10]
        return {"counts": counts, "total": len(data["candidates"]), "latest": newest}

    def get(self, candidate_id: str) -> dict | None:
        data = self._load()
        row = data["candidates"].get(candidate_id)
        if row is None:
            return None
        return {"id": candidate_id, **row}
