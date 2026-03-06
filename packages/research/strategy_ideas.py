from __future__ import annotations

import json
import pathlib
from typing import Any

REQUIRED_FIELDS = {
    "id",
    "name",
    "family",
    "description",
    "typical_market_regimes",
    "common_indicators",
    "tunable_parameters",
    "symbol_fit_notes",
    "known_strengths",
    "known_weaknesses",
    "implementation_status",
    "source_type",
    "strict_track_required",
    "priority_hint",
}

IMPLEMENTATION_STATUSES = {"idea_only", "partially_implemented", "implemented_plugin", "deprecated"}
SOURCE_TYPES = {"seed", "manual", "imported", "llm_generated"}
PRIORITY_HINTS = {"high", "medium", "low"}
IMPLEMENTED_PLUGIN_FAMILIES = {"TrendCore", "RangeMR"}


class StrategyIdeaLibrary:
    def __init__(self, ideas_dir: str = "strategy_ideas") -> None:
        self.ideas_dir = pathlib.Path(ideas_dir)
        self.ideas_dir.mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> pathlib.Path:
        return self.ideas_dir / "manifest.json"

    def _read_json(self, path: pathlib.Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _validate(self, row: dict[str, Any], source: str) -> tuple[bool, list[str]]:
        errors: list[str] = []
        missing = sorted(REQUIRED_FIELDS - set(row.keys()))
        if missing:
            errors.append(f"missing fields: {missing}")

        if row.get("implementation_status") not in IMPLEMENTATION_STATUSES:
            errors.append("invalid implementation_status")
        if row.get("source_type") not in SOURCE_TYPES:
            errors.append("invalid source_type")
        if row.get("priority_hint") not in PRIORITY_HINTS:
            errors.append("invalid priority_hint")
        if not isinstance(row.get("strict_track_required"), bool):
            errors.append("strict_track_required must be bool")

        if not isinstance(row.get("typical_market_regimes"), list):
            errors.append("typical_market_regimes must be list")
        if not isinstance(row.get("common_indicators"), list):
            errors.append("common_indicators must be list")
        if not isinstance(row.get("known_strengths"), list):
            errors.append("known_strengths must be list")
        if not isinstance(row.get("known_weaknesses"), list):
            errors.append("known_weaknesses must be list")
        if not isinstance(row.get("tunable_parameters"), dict):
            errors.append("tunable_parameters must be dict")

        if errors:
            return False, [f"{source}: {err}" for err in errors]
        return True, []

    def _priority_score(self, row: dict[str, Any]) -> float:
        by_hint = {"high": 1.0, "medium": 0.65, "low": 0.35}
        return by_hint.get(str(row.get("priority_hint", "medium")), 0.5)

    def _mapped_plugin(self, row: dict[str, Any]) -> str | None:
        mapped = row.get("mapped_plugin")
        if isinstance(mapped, str) and mapped in IMPLEMENTED_PLUGIN_FAMILIES:
            return mapped
        if row.get("family") in IMPLEMENTED_PLUGIN_FAMILIES and row.get("implementation_status") == "implemented_plugin":
            return str(row.get("family"))
        return None

    def load_manifest(self) -> dict[str, Any]:
        payload = self._read_json(self.manifest_path)
        return payload or {"version": 1, "ideas": []}

    def validate_manifest(self) -> dict[str, Any]:
        manifest = self.load_manifest()
        errors: list[str] = []
        idea_entries = manifest.get("ideas") if isinstance(manifest, dict) else []
        if not isinstance(idea_entries, list):
            return {"valid": False, "errors": ["manifest.ideas must be a list"], "idea_count": 0}

        file_ids = {x.get("id") for x in self.load()}
        manifest_ids = {x.get("id") for x in idea_entries if isinstance(x, dict)}
        missing_from_manifest = sorted(file_ids - manifest_ids)
        missing_from_files = sorted(manifest_ids - file_ids)
        if missing_from_manifest:
            errors.append(f"ids missing from manifest: {missing_from_manifest}")
        if missing_from_files:
            errors.append(f"ids missing from files: {missing_from_files}")
        return {"valid": not errors, "errors": errors, "idea_count": len(file_ids)}

    def load(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.ideas_dir.glob("*.json")):
            if path.name == "manifest.json":
                continue
            payload = self._read_json(path)
            if not payload:
                continue
            is_valid, _ = self._validate(payload, str(path.name))
            if is_valid:
                rows.append(payload)
        return rows

    def validation_report(self) -> dict[str, Any]:
        errors: list[str] = []
        valid_ids: list[str] = []
        for path in sorted(self.ideas_dir.glob("*.json")):
            if path.name == "manifest.json":
                continue
            payload = self._read_json(path)
            if payload is None:
                errors.append(f"{path.name}: invalid json")
                continue
            is_valid, row_errors = self._validate(payload, path.name)
            if is_valid:
                valid_ids.append(str(payload.get("id")))
            else:
                errors.extend(row_errors)

        seen = set()
        duplicates = []
        for rid in valid_ids:
            if rid in seen:
                duplicates.append(rid)
            seen.add(rid)
        if duplicates:
            errors.append(f"duplicate ids: {sorted(set(duplicates))}")

        manifest_report = self.validate_manifest()
        errors.extend(manifest_report.get("errors", []))
        return {
            "valid": not errors,
            "valid_count": len(valid_ids),
            "errors": errors,
            "manifest": manifest_report,
        }

    def report(self) -> dict[str, Any]:
        ideas = self.load()
        implemented = []
        idea_only = []
        strict_track = []
        partially_implemented = []

        for row in ideas:
            mapped_plugin = self._mapped_plugin(row)
            status = str(row.get("implementation_status"))
            item = {
                "id": row.get("id"),
                "name": row.get("name"),
                "family": row.get("family"),
                "implementation_status": status,
                "typical_market_regimes": row.get("typical_market_regimes", []),
                "symbol_fit_notes": row.get("symbol_fit_notes", ""),
                "tunable_parameters": row.get("tunable_parameters", {}),
                "source_type": row.get("source_type"),
                "mapped_plugin": mapped_plugin,
                "priority_hint": row.get("priority_hint"),
                "strict_track_required": bool(row.get("strict_track_required", True)),
            }
            if status == "implemented_plugin" and mapped_plugin:
                implemented.append(item)
            elif status == "partially_implemented":
                partially_implemented.append(item)
                strict_track.append({**item, "reason": "partial_implementation_requires_strict_review"})
            else:
                idea_only.append(item)
                if item["strict_track_required"]:
                    strict_track.append({**item, "reason": "requires_strategy_plugin_or_code_change"})

        return {
            "total": len(ideas),
            "implemented_plugins": implemented,
            "idea_only": idea_only,
            "partially_implemented": partially_implemented,
            "strict_track_candidates": strict_track,
            "proposed_for_future_implementation": [x for x in idea_only if x.get("priority_hint") == "high"],
            "manifest": self.load_manifest(),
            "validation": self.validation_report(),
        }

    def rank_for_symbol_regime(self, symbol: str, regime: str, limit: int = 6) -> list[dict[str, Any]]:
        regime_upper = regime.upper()
        symbol_upper = symbol.upper()
        scored: list[tuple[float, dict[str, Any]]] = []

        for row in self.load():
            score = self._priority_score(row)
            regimes = {str(x).upper() for x in row.get("typical_market_regimes", [])}
            symbol_notes = str(row.get("symbol_fit_notes", "")).upper()
            if regime_upper in regimes:
                score += 2.0
            if symbol_upper in symbol_notes or "ALL" in symbol_notes:
                score += 1.0
            if self._mapped_plugin(row):
                score += 0.75
            if row.get("implementation_status") == "idea_only":
                score += 0.2
            scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = []
        for score, row in scored[:limit]:
            top.append({
                "score": round(score, 3),
                "id": row.get("id"),
                "name": row.get("name"),
                "family": row.get("family"),
                "priority_hint": row.get("priority_hint"),
                "implementation_status": row.get("implementation_status"),
                "mapped_plugin": self._mapped_plugin(row),
                "typical_market_regimes": row.get("typical_market_regimes", []),
                "symbol_fit_notes": row.get("symbol_fit_notes", ""),
            })
        return top

    def summarize_for_llm(self, symbols: list[str], regimes: list[str], limit_per_pair: int = 3) -> dict[str, Any]:
        ideas = self.load()
        seed_rows = [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "family": row.get("family"),
                "implementation_status": row.get("implementation_status"),
                "mapped_plugin": self._mapped_plugin(row),
                "priority_hint": row.get("priority_hint"),
                "strict_track_required": row.get("strict_track_required"),
            }
            for row in ideas
        ]
        top_by_context: dict[str, list[dict[str, Any]]] = {}
        for symbol in symbols:
            for regime in regimes:
                key = f"{symbol}:{regime}"
                top_by_context[key] = self.rank_for_symbol_regime(symbol=symbol, regime=regime, limit=limit_per_pair)

        return {
            "total_ideas": len(ideas),
            "ideas": seed_rows,
            "top_ranked_by_symbol_regime": top_by_context,
            "validation": self.validation_report(),
        }
