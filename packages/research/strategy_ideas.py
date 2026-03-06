from __future__ import annotations

import json
import pathlib
from typing import Any


IMPLEMENTED_PLUGIN_FAMILIES = {"TrendCore", "RangeMR"}


class StrategyIdeaLibrary:
    def __init__(self, ideas_dir: str = "strategy_ideas") -> None:
        self.ideas_dir = pathlib.Path(ideas_dir)
        self.ideas_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.ideas_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("id") and payload.get("family"):
                rows.append(payload)
        return rows

    def report(self) -> dict[str, Any]:
        ideas = self.load()
        implemented = []
        pending = []
        strict_track = []
        for row in ideas:
            family = str(row.get("family", ""))
            item = {
                "id": row.get("id"),
                "name": row.get("name"),
                "family": family,
                "implementation_status": row.get("implementation_status", "idea_only"),
                "typical_market_regimes": row.get("typical_market_regimes", []),
                "tunable_parameters": row.get("tunable_parameters", {}),
                "source_type": row.get("source_type", "seed"),
            }
            if family in IMPLEMENTED_PLUGIN_FAMILIES:
                implemented.append(item)
            else:
                pending.append(item)
                strict_track.append({**item, "reason": "requires_strategy_plugin_or_code_change"})
        return {
            "total": len(ideas),
            "implemented_plugins": implemented,
            "idea_only": pending,
            "strict_track_candidates": strict_track,
        }

    def rank_for_symbol_regime(self, symbol: str, regime: str, limit: int = 6) -> list[dict[str, Any]]:
        regime = regime.upper()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self.load():
            score = 0.0
            regimes = {str(x).upper() for x in row.get("typical_market_regimes", [])}
            notes = str(row.get("symbol_fit_notes", "")).upper()
            family = str(row.get("family", ""))
            if regime in regimes:
                score += 2.0
            if symbol.upper() in notes or "ALL" in notes:
                score += 1.5
            if family in IMPLEMENTED_PLUGIN_FAMILIES:
                score += 1.0
            score += float(row.get("bootstrap_priority", 0.5))
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"score": round(score, 3), **row} for score, row in scored[:limit]]

