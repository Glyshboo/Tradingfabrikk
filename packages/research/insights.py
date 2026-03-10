from __future__ import annotations

from collections import defaultdict
from typing import Any


TARGET_FAMILIES = ["TrendCore", "RangeMR", "BreakoutRetest", "TrendPullback", "FailedBreakoutFade"]


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
    symbol_reason_counts = payload.get("symbol_reason_counts") or {}
    family_market_blocks = payload.get("family_market_quality_blocks") or {}
    reason_outcomes = payload.get("reason_outcome_stats") or {}
    quality_blocks = payload.get("quality_reason_counts") or {}

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

    symbol_patterns = []
    for symbol, counts in symbol_reason_counts.items():
        sorted_reasons = sorted((counts or {}).items(), key=lambda x: x[1], reverse=True)
        top_reason = sorted_reasons[0][0] if sorted_reasons else "unknown"
        total = int(sum(int(v or 0) for _, v in sorted_reasons))
        symbol_patterns.append(
            {
                "symbol": symbol,
                "total_no_trade": total,
                "top_reason": top_reason,
                "top_reason_count": sorted_reasons[0][1] if sorted_reasons else 0,
            }
        )
    symbol_patterns.sort(key=lambda x: x["total_no_trade"], reverse=True)

    gate_usefulness = []
    for reason, row in reason_outcomes.items():
        blocked = float((row or {}).get("blocked", 0.0) or 0.0)
        would_win = float((row or {}).get("would_win", 0.0) or 0.0)
        would_lose = float((row or {}).get("would_lose", 0.0) or 0.0)
        total = blocked if blocked > 0 else (would_win + would_lose)
        protect_rate = would_lose / max(total, 1.0)
        false_block_rate = would_win / max(total, 1.0)
        gate_usefulness.append(
            {
                "reason": reason,
                "blocked": int(blocked),
                "would_win": int(would_win),
                "would_lose": int(would_lose),
                "protect_rate": round(protect_rate, 6),
                "false_block_rate": round(false_block_rate, 6),
                "assessment": "protective" if protect_rate >= 0.55 else ("passive" if false_block_rate >= 0.45 else "mixed"),
            }
        )
    gate_usefulness.sort(key=lambda x: (x["assessment"] != "protective", -x["protect_rate"], x["false_block_rate"]))

    return {
        "total_no_trade_events": int(payload.get("total_no_trade_events", 0) or 0),
        "top_reasons": sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        "family_patterns": family_patterns,
        "symbol_patterns": symbol_patterns[:12],
        "family_market_quality_blocks": family_market_blocks,
        "quality_reason_counts": quality_blocks,
        "gate_usefulness": gate_usefulness[:12],
        "recent": payload.get("recent") or [],
    }


def build_quality_summary(candidates: list[dict], no_trade_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    no_trade_summary = no_trade_summary or {}
    market_components: dict[str, list[float]] = defaultdict(list)
    setup_components: dict[str, list[float]] = defaultdict(list)
    symbol_components: dict[str, list[float]] = defaultdict(list)
    symbol_scores: dict[str, list[float]] = defaultdict(list)

    for row in candidates:
        comp = row.get("strategy_composition") or {}
        regime = str(row.get("regime") or "unknown")
        symbol = str(row.get("symbol") or "unknown")
        family = str(row.get("strategy_family") or comp.get("entry_family") or "unknown")
        oos = row.get("oos_result") or {}
        challenger = row.get("challenger_result") or {}
        research_score = float(row.get("research_score") or 0.0)
        oos_pnl = float(oos.get("pnl") or 0.0)
        challenger_pnl = float(challenger.get("avg_pnl") or challenger.get("pnl") or 0.0)
        rejection_count = len(row.get("rejection_reasons") or [])
        sharpe_like = float(oos.get("sharpe_like") or 0.0)

        spread_sanity = 1.0 if regime != "ILLIQUID" else 0.2
        range_quality = 0.7 if regime in {"RANGE", "TREND_UP", "TREND_DOWN"} else 0.4
        compression_quality = 0.75 if family in {"BreakoutRetest", "TrendPullback"} else 0.55
        volatility_cleanliness = 0.7 if regime != "HIGH_VOL" else 0.45
        trend_clarity = 0.8 if regime in {"TREND_UP", "TREND_DOWN"} else 0.5
        feature_conflicts = max(0.0, min(1.0, 1.0 - 0.15 * rejection_count))
        liquidity_sanity = 0.85 if symbol not in {"unknown", "not available"} else 0.45
        market_score = (
            spread_sanity * 0.2
            + range_quality * 0.15
            + compression_quality * 0.1
            + volatility_cleanliness * 0.15
            + trend_clarity * 0.15
            + feature_conflicts * 0.1
            + liquidity_sanity * 0.15
        )

        family_fit = 0.75 if (family.startswith("Trend") and regime.startswith("TREND")) or (family == "RangeMR" and regime == "RANGE") else 0.45
        filter_agreement = 0.75 if comp.get("filter_pack") not in {None, "none", "safe"} else 0.55
        entry_strength = max(0.0, min(1.0, 0.5 + 0.4 * research_score))
        timing_quality = max(0.0, min(1.0, 0.5 + (0.1 if sharpe_like > 0 else -0.1)))
        recent_failure_context = max(0.0, min(1.0, 0.7 if not row.get("rejection_reasons") else 0.35))
        setup_score = family_fit * 0.25 + filter_agreement * 0.2 + entry_strength * 0.25 + timing_quality * 0.15 + recent_failure_context * 0.15

        liquidity_profile = liquidity_sanity
        recent_noise = max(0.0, min(1.0, 0.65 if regime == "HIGH_VOL" else 0.85))
        candidate_success = max(0.0, min(1.0, 0.5 + 0.15 * (oos_pnl + challenger_pnl)))
        no_trade_concentration = 1.0
        for row_nt in no_trade_summary.get("symbol_patterns") or []:
            if row_nt.get("symbol") == symbol:
                no_trade_concentration = max(0.0, min(1.0, 1.0 - (float(row_nt.get("total_no_trade", 0)) / 25.0)))
                break
        cost_quality = max(0.0, min(1.0, 0.75 + (0.05 if oos_pnl > 0 else -0.1)))
        symbol_score = liquidity_profile * 0.25 + recent_noise * 0.2 + candidate_success * 0.25 + no_trade_concentration * 0.15 + cost_quality * 0.15

        for k, v in {
            "spread_sanity": spread_sanity,
            "range_quality": range_quality,
            "compression_quality": compression_quality,
            "volatility_cleanliness": volatility_cleanliness,
            "trend_clarity": trend_clarity,
            "feature_conflicts": feature_conflicts,
            "liquidity_sanity": liquidity_sanity,
            "market_quality_score": market_score,
        }.items():
            market_components[k].append(v)
        for k, v in {
            "family_fit": family_fit,
            "filter_agreement": filter_agreement,
            "entry_strength": entry_strength,
            "timing_quality": timing_quality,
            "recent_failure_context": recent_failure_context,
            "setup_quality_score": setup_score,
        }.items():
            setup_components[k].append(v)
        for k, v in {
            "symbol_profile_liquidity": liquidity_profile,
            "recent_noise": recent_noise,
            "candidate_success": candidate_success,
            "no_trade_concentration": no_trade_concentration,
            "cost_quality": cost_quality,
            "symbol_quality_score": symbol_score,
        }.items():
            symbol_components[k].append(v)
        symbol_scores[symbol].append(symbol_score)

    def _avg_map(source: dict[str, list[float]]) -> dict[str, float]:
        return {k: round(_avg(v), 6) for k, v in source.items()}

    return {
        "market_quality": _avg_map(market_components),
        "setup_quality": _avg_map(setup_components),
        "symbol_quality": _avg_map(symbol_components),
        "symbol_quality_ranking": [
            {"symbol": sym, "quality_score": round(_avg(vals), 6), "samples": len(vals)}
            for sym, vals in sorted(symbol_scores.items(), key=lambda item: _avg(item[1]), reverse=True)
        ],
    }


def build_family_profiles(
    candidates: list[dict],
    attribution: dict[str, Any] | None = None,
    no_trade_summary: dict[str, Any] | None = None,
    performance_memory_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attribution = attribution or {}
    no_trade_summary = no_trade_summary or {}
    perf_cells = (performance_memory_snapshot or {}).get("top_cells") or []

    family_rows: dict[str, list[dict]] = defaultdict(list)
    for row in candidates:
        family = str(row.get("strategy_family") or (row.get("strategy_composition") or {}).get("entry_family") or "unknown")
        family_rows[family].append(row)

    filter_summary = attribution.get("filter_module_summary") or []
    exit_summary = attribution.get("exit_pack_summary") or []
    family_no_trade = {row.get("family"): row for row in (no_trade_summary.get("family_patterns") or [])}

    profiles = {}
    for family in TARGET_FAMILIES:
        rows = family_rows.get(family, [])
        regime_edge: dict[str, list[float]] = defaultdict(list)
        symbol_edge: dict[str, list[float]] = defaultdict(list)
        cost_scores: list[float] = []
        for row in rows:
            regime = str(row.get("regime") or "unknown")
            symbol = str(row.get("symbol") or "unknown")
            oos = float((row.get("oos_result") or {}).get("pnl") or 0.0)
            challenger = float((row.get("challenger_result") or {}).get("avg_pnl") or (row.get("challenger_result") or {}).get("pnl") or 0.0)
            research = float(row.get("research_score") or 0.0)
            edge = research + 0.15 * oos + 0.25 * challenger
            regime_edge[regime].append(edge)
            symbol_edge[symbol].append(edge)
            cost_scores.append(1.0 if oos > 0 else 0.35)

        preferred_regimes = sorted(regime_edge.items(), key=lambda item: _avg(item[1]), reverse=True)[:3]
        harmful_regimes = sorted(regime_edge.items(), key=lambda item: _avg(item[1]))[:3]
        symbol_affinity = sorted(symbol_edge.items(), key=lambda item: _avg(item[1]), reverse=True)[:5]
        helpful_filters = [r for r in filter_summary if r.get("family") == family and r.get("impact") == "improves"][:5]
        harmful_filters = [r for r in filter_summary if r.get("family") == family and r.get("impact") == "harms"][:5]
        helpful_exits = [r for r in exit_summary if r.get("family") == family and r.get("impact") == "improves"][:4]
        harmful_exits = [r for r in exit_summary if r.get("family") == family and r.get("impact") == "harms"][:4]
        no_trade = family_no_trade.get(family, {})
        market_blocks = int((no_trade_summary.get("family_market_quality_blocks") or {}).get(family, 0) or 0)
        perf_family = [c for c in perf_cells if c.get("strategy_family") == family]
        failure_mode = "limited_data"
        if harmful_filters:
            failure_mode = f"filter_conflict:{harmful_filters[0].get('name')}"
        elif harmful_regimes and harmful_regimes[0][1]:
            failure_mode = f"regime_mismatch:{harmful_regimes[0][0]}"

        confidence = min(1.0, (len(rows) + len(perf_family) + int(no_trade.get("observed", 0) or 0)) / 18.0)
        profiles[family] = {
            "samples": len(rows),
            "preferred_regimes": [{"regime": k, "avg_edge": round(_avg(v), 6), "samples": len(v)} for k, v in preferred_regimes],
            "harmful_regimes": [{"regime": k, "avg_edge": round(_avg(v), 6), "samples": len(v)} for k, v in harmful_regimes],
            "helpful_filters": helpful_filters,
            "harmful_filters": harmful_filters,
            "helpful_exits": helpful_exits,
            "harmful_exits": harmful_exits,
            "symbol_affinity": [{"symbol": k, "avg_edge": round(_avg(v), 6), "samples": len(v)} for k, v in symbol_affinity],
            "cost_sensitivity": round(1.0 - _avg(cost_scores), 6) if cost_scores else 0.0,
            "no_trade_sensitivity": {
                "top_reason": no_trade.get("top_reason", "unknown"),
                "top_reason_count": int(no_trade.get("top_reason_count", 0) or 0),
                "avg_setup_quality_when_blocked": float(no_trade.get("avg_setup_quality", 0.0) or 0.0),
                "market_quality_blocks": market_blocks,
            },
            "typical_failure_modes": [failure_mode],
            "current_confidence": round(confidence, 6),
            "confidence_note": "observational_profile_not_causal",
        }

    return {"family_profiles": profiles}
