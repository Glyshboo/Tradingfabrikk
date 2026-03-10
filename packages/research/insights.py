from __future__ import annotations

from collections import defaultdict
from typing import Any


def _label(delta: float, min_effect: float = 0.03) -> str:
    if delta >= min_effect:
        return "improves"
    if delta <= -min_effect:
        return "harms"
    return "neutral"


def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def build_family_filter_exit_attribution(candidates: list[dict], ranking: dict[str, list[dict]] | None = None) -> dict[str, Any]:
    ranking = ranking or {}
    observations: list[dict[str, Any]] = []

    for row in candidates:
        comp = (row.get("strategy_composition") or {}) if isinstance(row, dict) else {}
        family = row.get("strategy_family") or comp.get("entry_family")
        if not family:
            continue
        quality = float(row.get("research_score") or 0.0)
        oos_pnl = float((row.get("oos_result") or {}).get("pnl") or 0.0)
        challenger = float((row.get("challenger_result") or {}).get("avg_pnl") or (row.get("challenger_result") or {}).get("pnl") or 0.0)
        combined_edge = quality + (0.15 * oos_pnl) + (0.25 * challenger)
        observations.append(
            {
                "family": family,
                "filter_pack": comp.get("filter_pack", "safe"),
                "filter_modules": comp.get("filter_modules") or [],
                "exit_pack": comp.get("exit_pack", "passthrough"),
                "edge": combined_edge,
            }
        )

    for rows in (ranking or {}).values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            comp = (row.get("strategy_composition") or {}) if isinstance(row, dict) else {}
            family = row.get("strategy_family") or comp.get("entry_family")
            if not family:
                continue
            observations.append(
                {
                    "family": family,
                    "filter_pack": comp.get("filter_pack", "safe"),
                    "filter_modules": comp.get("filter_modules") or [],
                    "exit_pack": comp.get("exit_pack", "passthrough"),
                    "edge": float(row.get("score") or 0.0),
                }
            )

    by_family: dict[str, list[float]] = defaultdict(list)
    by_filter_pack: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_filter_module: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_exit_pack: dict[tuple[str, str], list[float]] = defaultdict(list)

    for obs in observations:
        family = obs["family"]
        by_family[family].append(obs["edge"])
        by_filter_pack[(family, str(obs["filter_pack"]))].append(obs["edge"])
        by_exit_pack[(family, str(obs["exit_pack"]))].append(obs["edge"])
        for module in obs["filter_modules"]:
            by_filter_module[(family, str(module))].append(obs["edge"])

    family_summary = [
        {"family": family, "samples": len(vals), "avg_edge": round(_avg(vals), 6)}
        for family, vals in sorted(by_family.items(), key=lambda item: _avg(item[1]), reverse=True)
    ]

    def _summarize(keyed: dict[tuple[str, str], list[float]], by_family_values: dict[str, list[float]]) -> list[dict]:
        rows = []
        for (family, name), vals in keyed.items():
            fam_avg = _avg(by_family_values.get(family, []))
            avg_edge = _avg(vals)
            delta = avg_edge - fam_avg
            rows.append(
                {
                    "family": family,
                    "name": name,
                    "samples": len(vals),
                    "avg_edge": round(avg_edge, 6),
                    "delta_vs_family": round(delta, 6),
                    "impact": _label(delta),
                }
            )
        return sorted(rows, key=lambda r: (r["impact"] != "improves", -r["delta_vs_family"]))

    return {
        "family_summary": family_summary,
        "filter_pack_summary": _summarize(by_filter_pack, by_family),
        "filter_module_summary": _summarize(by_filter_module, by_family),
        "exit_pack_summary": _summarize(by_exit_pack, by_family),
    }


def summarize_no_trade_intelligence(no_trade_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = no_trade_payload or {}
    reason_counts = payload.get("reason_counts") or {}
    family_reason_counts = payload.get("family_reason_counts") or {}
    family_quality = payload.get("family_quality") or {}

    family_patterns = []
    for family, counts in family_reason_counts.items():
        sorted_reasons = sorted((counts or {}).items(), key=lambda x: x[1], reverse=True)
        quality_row = family_quality.get(family, {})
        observed = int(quality_row.get("observed", 0) or 0)
        avg_quality = float(quality_row.get("setup_quality_sum", 0.0) or 0.0) / max(1, observed)
        family_patterns.append(
            {
                "family": family,
                "top_reason": sorted_reasons[0][0] if sorted_reasons else "unknown",
                "top_reason_count": sorted_reasons[0][1] if sorted_reasons else 0,
                "avg_setup_quality": round(avg_quality, 6),
                "observed": observed,
            }
        )

    family_patterns.sort(key=lambda x: x["top_reason_count"], reverse=True)
    return {
        "total_no_trade_events": int(payload.get("total_no_trade_events", 0) or 0),
        "top_reasons": sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        "family_patterns": family_patterns,
        "recent": payload.get("recent") or [],
    }
