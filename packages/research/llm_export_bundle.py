from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from packages.research.insights import (
    build_family_filter_exit_attribution,
    build_family_profiles,
    build_quality_summary,
    summarize_no_trade_intelligence,
)


NOT_AVAILABLE = "not available"


class ResearchBundleExporter:
    def __init__(
        self,
        *,
        status_file: str = "runtime/status.json",
        registry_file: str = "runtime/candidates_registry.json",
        engine_state_file: str = "runtime/engine_state.json",
        review_queue_file: str = "runtime/review_queue.json",
        ranking_file: str = "configs/candidates/ranking.json",
        output_dir: str = "runtime/llm_exports",
    ) -> None:
        self.status_path = Path(status_file)
        self.registry_path = Path(registry_file)
        self.engine_state_path = Path(engine_state_file)
        self.review_queue_path = Path(review_queue_file)
        self.ranking_path = Path(ranking_file)
        self.output_dir = Path(output_dir)

    def _safe_json(self, path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback

    def _load_sources(self) -> dict:
        return {
            "status": self._safe_json(self.status_path, {}),
            "registry": self._safe_json(self.registry_path, {"candidates": {}}),
            "engine_state": self._safe_json(self.engine_state_path, {}),
            "review_queue": self._safe_json(self.review_queue_path, {"queue": [], "history": []}),
            "ranking": self._safe_json(self.ranking_path, {}),
        }

    def _candidate_rows(self, registry_payload: dict) -> list[dict]:
        rows = []
        for candidate_id, row in (registry_payload.get("candidates") or {}).items():
            meta = row.get("meta") or {}
            artifacts = row.get("artifacts") or {}
            symbols = row.get("symbols") or meta.get("symbols") or []
            regimes = row.get("regimes") or meta.get("regimes") or []
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "strategy_family": row.get("strategy_family") or meta.get("strategy_family") or NOT_AVAILABLE,
                    "symbol": (symbols[0] if symbols else (meta.get("symbol") or NOT_AVAILABLE)),
                    "regime": (regimes[0] if regimes else (meta.get("regime") or NOT_AVAILABLE)),
                    "current_state": row.get("state") or NOT_AVAILABLE,
                    "research_score": row.get("score"),
                    "plausible": meta.get("plausible", (meta.get("evaluation") or {}).get("plausible", NOT_AVAILABLE)),
                    "rejection_reasons": meta.get("rejection_reasons") or (meta.get("evaluation") or {}).get("rejection_reasons") or [],
                    "oos_result": artifacts.get("oos_result") or meta.get("oos_result") or {},
                    "challenger_result": artifacts.get("paper_challenger_result") or meta.get("paper_challenger_result") or {},
                    "learned_adjustment": meta.get("learned_adjustment", NOT_AVAILABLE),
                    "uncertainty_penalty": meta.get("uncertainty_penalty", NOT_AVAILABLE),
                    "recommendation": artifacts.get("recommendation") or meta.get("recommendation") or NOT_AVAILABLE,
                    "strategy_composition": row.get("strategy_composition") or meta.get("strategy_composition") or {},
                    "updated_ts": row.get("updated_ts", 0),
                }
            )
        rows.sort(key=lambda x: (bool(x.get("plausible")), x.get("research_score") or -9999, x.get("updated_ts") or 0), reverse=True)
        return rows

    def _performance_memory_snapshot(self, engine_state: dict) -> dict:
        memory_state = engine_state.get("performance_memory_state") or {}
        parsed = []
        for key, cell in memory_state.items():
            parts = str(key).split("|")
            if len(parts) != 4:
                continue
            parsed.append(
                {
                    "symbol": parts[0],
                    "regime": parts[1],
                    "strategy_family": parts[2],
                    "config": parts[3],
                    "sample_count": float(cell.get("sample_count", 0.0)),
                    "recent_pnl": float(cell.get("recent_pnl", 0.0)),
                    "hit_rate": float(cell.get("hit_rate", 0.5)),
                    "avg_result": float(cell.get("avg_result", 0.0)),
                    "challenger_relative": float(cell.get("challenger_relative", 0.0)),
                }
            )
        parsed.sort(key=lambda x: (x["sample_count"], abs(x["recent_pnl"])), reverse=True)
        return {
            "total_cells": len(parsed),
            "top_cells": parsed[:8],
        }

    def _selector_summary(self, status: dict) -> dict:
        decision = status.get("last_decision") or {}
        return {
            "blocked_reason": decision.get("blocked_reason", NOT_AVAILABLE),
            "selected_candidate": decision.get("selected_candidate", NOT_AVAILABLE),
            "eligible_strategies": decision.get("eligible_strategies") or [],
            "score_components": decision.get("score_components") or {},
            "score_breakdown": decision.get("score_breakdown") or {},
        }

    def _failure_patterns(self, candidates: list[dict], status: dict, engine_state: dict) -> dict:
        reason_counter: Counter[str] = Counter()
        symbol_counter: Counter[str] = Counter()
        regime_counter: Counter[str] = Counter()
        strategy_counter: Counter[str] = Counter()
        state_counter: Counter[str] = Counter()

        failure_states = {"validation_failed", "rejected", "paper_candidate_fading", "edge_decay", "needs_revalidation", "paper_candidate_fail"}
        for row in candidates:
            is_failure = (row.get("current_state") in failure_states) or (row.get("plausible") is False)
            if not is_failure:
                continue
            for reason in row.get("rejection_reasons") or ["unknown_failure_reason"]:
                reason_counter[str(reason)] += 1
            symbol_counter[str(row.get("symbol") or NOT_AVAILABLE)] += 1
            regime_counter[str(row.get("regime") or NOT_AVAILABLE)] += 1
            strategy_counter[str(row.get("strategy_family") or NOT_AVAILABLE)] += 1
            state_counter[str(row.get("current_state") or NOT_AVAILABLE)] += 1

        challenger_rows = (status.get("paper_candidate") or {}).get("challenger_evaluations") or engine_state.get("challenger_eval_history") or []
        recent_challenger_failures = [
            row for row in challenger_rows[-20:] if float((row.get("challenger_pnl") or row.get("pnl") or 0.0)) < 0
        ]

        return {
            "top_rejection_reasons": reason_counter.most_common(8),
            "failure_symbols": symbol_counter.most_common(6),
            "failure_regimes": regime_counter.most_common(6),
            "failure_strategies": strategy_counter.most_common(6),
            "failure_states": state_counter.most_common(8),
            "recent_challenger_failures": recent_challenger_failures,
        }

    def _format_executive_summary(self, bundle: dict) -> str:
        top = bundle.get("top_candidates") or []
        failures = bundle.get("top_failure_patterns") or {}
        best = [c for c in top if c.get("plausible") is True][:3]
        worst = [c for c in top if c.get("plausible") is False][:3]
        incubation = [c for c in top if c.get("current_state") in {"paper_candidate_active", "challenger_active", "paper_smoke_running", "paper_smoke_pass"}][:5]

        def _line(rows: list[dict]) -> str:
            if not rows:
                return f"- {NOT_AVAILABLE}"
            return "\n".join(
                f"- {r['candidate_id']} ({r['strategy_family']} / {r['symbol']} / {r['regime']}) score={r.get('research_score', NOT_AVAILABLE)}"
                for r in rows
            )

        learn = bundle.get("performance_memory_snapshot") or {}
        selector = bundle.get("selector_summary") or {}
        reasons = failures.get("top_rejection_reasons") or []
        family_attr = (bundle.get("family_filter_exit_attribution") or {}).get("family_summary") or []
        best_families = "\n".join(
            f"- {row.get('family')}: avg_edge={row.get('avg_edge')} (samples={row.get('samples')})"
            for row in family_attr[:4]
        ) or f"- {NOT_AVAILABLE}"
        no_trade = bundle.get("no_trade_intelligence") or {}
        nt_reasons = "\n".join(f"- {name}: {count}" for name, count in (no_trade.get("top_reasons") or [])[:5]) or f"- {NOT_AVAILABLE}"
        quality = bundle.get("quality_summaries") or {}
        market_q = (quality.get("market_quality") or {}).get("market_quality_score", NOT_AVAILABLE)
        setup_q = (quality.get("setup_quality") or {}).get("setup_quality_score", NOT_AVAILABLE)
        symbol_q = (quality.get("symbol_quality") or {}).get("symbol_quality_score", NOT_AVAILABLE)
        family_profiles = (bundle.get("family_profiles") or {}).get("family_profiles") or {}
        profile_lines = []
        for family, row in list(family_profiles.items())[:4]:
            preferred = ((row.get("preferred_regimes") or [{}])[0]).get("regime", "unknown")
            harmful = ((row.get("harmful_regimes") or [{}])[0]).get("regime", "unknown")
            profile_lines.append(f"- {family}: preferred={preferred}, harmful={harmful}, confidence={row.get('current_confidence', 0)}")
        profile_text = "\n".join(profile_lines) or f"- {NOT_AVAILABLE}"

        return (
            "# Executive Summary\n\n"
            "## Hva fungerer best nå\n"
            f"{_line(best)}\n\n"
            "## Hva fungerer dårligst nå\n"
            f"{_line(worst)}\n\n"
            "## Beste challengers / kandidater under incubation\n"
            f"{_line(incubation)}\n\n"
            "## Tydelige failure patterns\n"
            + ("\n".join(f"- {name}: {count}" for name, count in reasons) if reasons else f"- {NOT_AVAILABLE}")
            + "\n\n## Hva selector/performance memory ser ut til å lære\n"
            f"- Last blocked reason: {selector.get('blocked_reason', NOT_AVAILABLE)}\n"
            f"- Performance memory cells: {learn.get('total_cells', 0)}\n"
            "\n## Family performance summary\n"
            f"{best_families}\n"
            "\n## Family profiling snapshot\n"
            f"{profile_text}\n"
            "\n## Quality diagnostics\n"
            f"- Market quality score: {market_q}\n"
            f"- Setup quality score: {setup_q}\n"
            f"- Symbol quality score: {symbol_q}\n"
            "\n## No-trade reason summary\n"
            f"{nt_reasons}\n"
            "\n## Hva systemet bør forske mer på neste runde\n"
            "- Prioriter symbol/regime-kombinasjoner med høy failure-rate, men der rejection skyldes få trades eller kostnads-sensitivitet.\n"
            "- Foreslå små, testbare endringer i filters, regime-regler og search-space fremfor brede redesign.\n"
        )

    def _format_top_candidates(self, top_candidates: list[dict]) -> str:
        header = (
            "# Top Candidates\n\n"
            "| candidate_id | strategy_family | symbol | regime | current_state | research_score | family-fit context | plausible/rejection reasons | OOS pnl | OOS sharpe_like | challenger/paper result | learned adjustment | uncertainty penalty | recommendation |\n"
            "|---|---|---|---|---|---:|---|---|---:|---:|---|---:|---:|---|\n"
        )
        rows = []
        for row in top_candidates:
            oos = row.get("oos_result") or {}
            challenger = row.get("challenger_result") or {}
            plausible_text = str(row.get("plausible", NOT_AVAILABLE))
            if row.get("rejection_reasons"):
                plausible_text += " / " + ", ".join(str(x) for x in row.get("rejection_reasons")[:3])
            challenger_text = challenger if challenger else NOT_AVAILABLE
            composition = row.get("strategy_composition") or {}
            family_fit = f"filter={composition.get('filter_pack', 'safe')}, exit={composition.get('exit_pack', 'passthrough')}"
            rows.append(
                "| {candidate_id} | {strategy_family} | {symbol} | {regime} | {current_state} | {score} | {family_fit} | {plausible} | {oos_pnl} | {oos_sharpe} | {challenger} | {learned} | {uncertainty} | {recommendation} |".format(
                    candidate_id=row.get("candidate_id", NOT_AVAILABLE),
                    strategy_family=row.get("strategy_family", NOT_AVAILABLE),
                    symbol=row.get("symbol", NOT_AVAILABLE),
                    regime=row.get("regime", NOT_AVAILABLE),
                    current_state=row.get("current_state", NOT_AVAILABLE),
                    score=row.get("research_score", NOT_AVAILABLE),
                    family_fit=family_fit,
                    plausible=plausible_text,
                    oos_pnl=oos.get("pnl", NOT_AVAILABLE),
                    oos_sharpe=oos.get("sharpe_like", NOT_AVAILABLE),
                    challenger=str(challenger_text).replace("|", "/"),
                    learned=row.get("learned_adjustment", NOT_AVAILABLE),
                    uncertainty=row.get("uncertainty_penalty", NOT_AVAILABLE),
                    recommendation=row.get("recommendation", NOT_AVAILABLE),
                )
            )
        if not rows:
            rows = [f"| {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} | {NOT_AVAILABLE} |"]
        return header + "\n".join(rows) + "\n"

    def _format_failure_report(self, failure_patterns: dict, attribution: dict, no_trade: dict, quality: dict) -> str:
        def _render_pairs(title: str, pairs: list[tuple]) -> str:
            body = "\n".join(f"- {name}: {count}" for name, count in pairs) if pairs else f"- {NOT_AVAILABLE}"
            return f"## {title}\n{body}\n"

        recent = failure_patterns.get("recent_challenger_failures") or []
        recent_text = "\n".join(
            f"- candidate={row.get('candidate_id', NOT_AVAILABLE)} pnl={row.get('challenger_pnl', row.get('pnl', NOT_AVAILABLE))} symbol={row.get('symbol', NOT_AVAILABLE)} regime={row.get('regime', NOT_AVAILABLE)}"
            for row in recent[:8]
        ) or f"- {NOT_AVAILABLE}"

        interpretation = "Funnene tyder på at robusthet svekkes når kandidater har lav sample-støtte, negativ OOS etter kostnader, eller fallende challenger-resultater. Prioriter strengere filtre og revalidering før videre promotering."
        weak_filters = [r for r in (attribution.get("filter_module_summary") or []) if r.get("impact") == "harms"][:6]
        weak_exits = [r for r in (attribution.get("exit_pack_summary") or []) if r.get("impact") == "harms"][:6]
        family_patterns = no_trade.get("family_patterns") or []
        symbol_patterns = no_trade.get("symbol_patterns") or []
        gate_usefulness = no_trade.get("gate_usefulness") or []
        market_quality = quality.get("market_quality") or {}

        return (
            "# Failure Report\n\n"
            + _render_pairs("Vanligste rejection reasons", failure_patterns.get("top_rejection_reasons") or [])
            + _render_pairs("Strategier/symboler/regimer som går igjen i failures", failure_patterns.get("failure_strategies") or [])
            + _render_pairs("State-mønstre (inkl. edge_decay / needs_revalidation)", failure_patterns.get("failure_states") or [])
            + _render_pairs("Filter modules som ofte ser ut til å skade edge", [(f"{r.get('family')}::{r.get('name')}", r.get("samples", 0)) for r in weak_filters])
            + _render_pairs("Exit packs som ofte ser ut til å skade edge", [(f"{r.get('family')}::{r.get('name')}", r.get("samples", 0)) for r in weak_exits])
            + _render_pairs("No-trade patterns per family", [(f"{r.get('family')}::{r.get('top_reason')}", r.get("top_reason_count", 0)) for r in family_patterns[:8]])
            + _render_pairs("No-trade patterns per symbol", [(f"{r.get('symbol')}::{r.get('top_reason')}", r.get("top_reason_count", 0)) for r in symbol_patterns[:8]])
            + _render_pairs("No-trade gates som virker protective", [(r.get("reason"), f"protect={r.get('protect_rate')}") for r in gate_usefulness[:6]])
            + "## Market quality baseline\n"
            + "\n".join(f"- {name}: {val}" for name, val in market_quality.items())
            + "## Siste tydelige feilmønstre\n"
            + recent_text
            + "\n\n## Praktisk tolkning\n"
            + f"- {interpretation}\n"
        )

    def _format_paste_to_llm(self, executive_summary: str, top_candidates_md: str, failure_report_md: str, bundle: dict) -> str:
        response_format = self._format_llm_response_template()
        attr = bundle.get("family_filter_exit_attribution") or {}
        no_trade = bundle.get("no_trade_intelligence") or {}
        family_profiles = (bundle.get("family_profiles") or {}).get("family_profiles") or {}
        quality = bundle.get("quality_summaries") or {}
        family_lines = "\n".join(
            f"- {row.get('family')}: avg_edge={row.get('avg_edge')} samples={row.get('samples')}"
            for row in (attr.get("family_summary") or [])[:6]
        ) or f"- {NOT_AVAILABLE}"
        no_trade_lines = "\n".join(f"- {name}: {count}" for name, count in (no_trade.get("top_reasons") or [])[:6]) or f"- {NOT_AVAILABLE}"
        profile_lines = "\n".join(
            f"- {family}: preferred={((row.get('preferred_regimes') or [{}])[0]).get('regime', 'unknown')} harmful={((row.get('harmful_regimes') or [{}])[0]).get('regime', 'unknown')} confidence={row.get('current_confidence', 0)}"
            for family, row in list(family_profiles.items())[:6]
        ) or f"- {NOT_AVAILABLE}"
        quality_lines = "\n".join(
            f"- {name}: {value}" for name, value in {
                "market_quality_score": (quality.get("market_quality") or {}).get("market_quality_score", NOT_AVAILABLE),
                "setup_quality_score": (quality.get("setup_quality") or {}).get("setup_quality_score", NOT_AVAILABLE),
                "symbol_quality_score": (quality.get("symbol_quality") or {}).get("symbol_quality_score", NOT_AVAILABLE),
            }.items()
        )
        return (
            "# Paste to LLM\n\n"
            "## Systeminstruksjon til LLM\n"
            "Du er en konservativ research-assistent for crypto futures. Ikke foreslå live deploy, og ikke foreslå endringer som bryter fail-closed/risk-guardrails.\n\n"
            "## Eksplisitt mål\n"
            "Finn robuste nye research-idéer med fokus på netto-edge etter kostnader (fees/slippage/funding), og prioriter testbare hypoteser fremfor komplekse modeller.\n\n"
            "## Executive summary\n\n"
            f"{executive_summary}\n\n"
            "## Top candidates\n\n"
            f"{top_candidates_md}\n\n"
            "## Failure patterns\n\n"
            f"{failure_report_md}\n\n"
            "## Family/filter/exit attribution snapshot\n"
            f"{family_lines}\n\n"
            "## Family profile snapshot\n"
            f"{profile_lines}\n\n"
            "## Quality diagnostics snapshot\n"
            f"{quality_lines}\n\n"
            "## No-trade intelligence snapshot\n"
            f"{no_trade_lines}\n\n"
            "## Oppgave til LLM\n"
            "Foreslå 8 konkrete neste steg fordelt på: (1) config changes, (2) search-space changes, (3) regime/selector changes, (4) nye strategy ideas.\n"
            "Skriv svaret ditt i nøyaktig formatet under. Ikke bruk andre toppnivå-felt.\n\n"
            "## Påkrevd svarformat (kopier og fyll ut)\n\n"
            f"{response_format}\n\n"
            "## Kvalitetskrav for hvert forslag\n"
            "- Vær konkret og kort. Unngå diffuse anbefalinger.\n"
            "- Skill tydelig mellom forslag som er config-only, search-space-only, eller code-level.\n"
            "- Hvis requires_code=true må du si nøyaktig hva som må implementeres.\n"
            "- Hvis requires_code=false skal forslaget kunne testes uten nye Python-filer.\n"
            "- Koble alltid forslag til validation-plan (backtest + OOS + paper) med fail-fast kriterier.\n\n"
            "## Viktig\n"
            "Unngå overfitting. Fokuser på små, verifiserbare endringer med høy forklarbarhet og klar fail-fast evaluering.\n"
        )

    def _format_llm_response_template(self) -> str:
        return (
            "```markdown\n"
            "# LLM Research Response\n\n"
            "## config_changes\n"
            "- id: cfg_1\n"
            "  summary: Kort beskrivelse av config-endring\n"
            "  proposed_change: Konkret verdi/endring i YAML/JSON\n"
            "  why_this_may_have_edge: Hvorfor dette kan bedre netto-edge\n"
            "  how_to_validate: Backtest + OOS + paper plan med stop-kriterier\n"
            "  requires_code: false\n\n"
            "## search_space_changes\n"
            "- id: ss_1\n"
            "  summary: Kort beskrivelse av endring i research-space\n"
            "  proposed_change: Hvilke grenser/parametre/symboler/regimer som endres\n"
            "  why_this_may_have_edge: Hvorfor søkeområdet blir bedre\n"
            "  how_to_validate: Hvordan måle at søkeområdet forbedres\n"
            "  requires_code: false\n\n"
            "## regime_or_selector_changes\n"
            "- id: reg_1\n"
            "  summary: Endring i regime- eller selector-logikk\n"
            "  proposed_change: Konkret tweak (terskel, penalty, gating, osv.)\n"
            "  why_this_may_have_edge: Hvorfor dette kan redusere dårlige valg\n"
            "  how_to_validate: Evaluering mot feilvalg/edge decay\n"
            "  requires_code: true\n\n"
            "## new_strategy_ideas\n"
            "- id: idea_1\n"
            "  summary: Ny strategi-idé\n"
            "  setup: Markedssituasjon + trigger + exit-idé\n"
            "  why_this_may_have_edge: Hvorfor markedet kan være ineffisient her\n"
            "  how_to_validate: Enkel valideringsplan før eventuell implementering\n"
            "  requires_code: true\n\n"
            "## requires_code\n"
            "- config_changes: false\n"
            "- search_space_changes: false\n"
            "- regime_or_selector_changes: true\n"
            "- new_strategy_ideas: true\n\n"
            "## notes_for_codex\n"
            "- Prioriter rekkefølge (1-3) for hva som bør gjøres først\n"
            "- Merk eksplisitt hva som kan gjøres uten kode\n"
            "```\n"
        )

    def build_bundle(self) -> tuple[dict, dict[str, str]]:
        sources = self._load_sources()
        status = sources["status"]
        registry = sources["registry"]
        engine_state = sources["engine_state"]
        ranking = sources["ranking"]

        candidates = self._candidate_rows(registry)
        top_candidates = candidates[:12]
        candidate_state_counts = dict(Counter(row.get("current_state", NOT_AVAILABLE) for row in candidates))
        failure_patterns = self._failure_patterns(candidates, status, engine_state)
        attribution = build_family_filter_exit_attribution(candidates, ranking if isinstance(ranking, dict) else {})
        no_trade = summarize_no_trade_intelligence(status.get("no_trade_diagnostics") or engine_state.get("no_trade_diagnostics") or {})
        quality = build_quality_summary(candidates, no_trade)
        family_profiles = build_family_profiles(candidates, attribution, no_trade, self._performance_memory_snapshot(engine_state))

        promising_filters = [x for x in (attribution.get("filter_module_summary") or []) if x.get("impact") == "improves"][:8]
        dead_end_filters = [x for x in (attribution.get("filter_module_summary") or []) if x.get("impact") == "harms"][:8]
        promising_exits = [x for x in (attribution.get("exit_pack_summary") or []) if x.get("impact") == "improves"][:8]
        dead_end_exits = [x for x in (attribution.get("exit_pack_summary") or []) if x.get("impact") == "harms"][:8]

        bundle = {
            "generated_ts": time.time(),
            "mode_status_summary": {
                "mode": status.get("mode", NOT_AVAILABLE),
                "state": status.get("state", NOT_AVAILABLE),
                "safe_pause": status.get("safe_pause", NOT_AVAILABLE),
                "reduce_only": status.get("reduce_only", NOT_AVAILABLE),
            },
            "current_regime_summary": status.get("current_regime") or {},
            "top_candidates": top_candidates,
            "candidate_state_counts": candidate_state_counts,
            "recent_challenger_evaluations": (status.get("paper_candidate") or {}).get("challenger_evaluations") or engine_state.get("challenger_eval_history") or [],
            "performance_memory_snapshot": self._performance_memory_snapshot(engine_state),
            "selector_summary": self._selector_summary(status),
            "top_failure_patterns": failure_patterns,
            "family_filter_exit_attribution": attribution,
            "family_profiles": family_profiles,
            "quality_summaries": quality,
            "no_trade_intelligence": no_trade,
            "research_recommendations": {
                "promising_filters": promising_filters,
                "dead_end_filters": dead_end_filters,
                "promising_exits": promising_exits,
                "dead_end_exits": dead_end_exits,
            },
            "recent_research_rankings": ranking if isinstance(ranking, dict) else {},
            "important_sources": [
                {"path": str(self.status_path), "exists": self.status_path.exists()},
                {"path": str(self.registry_path), "exists": self.registry_path.exists()},
                {"path": str(self.engine_state_path), "exists": self.engine_state_path.exists()},
                {"path": str(self.review_queue_path), "exists": self.review_queue_path.exists()},
                {"path": str(self.ranking_path), "exists": self.ranking_path.exists()},
            ],
        }

        executive_summary = self._format_executive_summary(bundle)
        top_candidates_md = self._format_top_candidates(top_candidates)
        failure_report_md = self._format_failure_report(failure_patterns, attribution, no_trade, quality)
        paste_to_llm_md = self._format_paste_to_llm(executive_summary, top_candidates_md, failure_report_md, bundle)

        return bundle, {
            "executive_summary.md": executive_summary,
            "top_candidates.md": top_candidates_md,
            "failure_report.md": failure_report_md,
            "research_bundle.json": json.dumps(bundle, indent=2),
            "paste_to_llm.md": paste_to_llm_md,
            "llm_response_template.md": self._format_llm_response_template(),
        }

    def export(self) -> dict[str, str]:
        bundle, outputs = self.build_bundle()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        written = {}
        for filename, content in outputs.items():
            path = self.output_dir / filename
            path.write_text(content, encoding="utf-8")
            written[filename] = str(path)
        return {"output_dir": str(self.output_dir), "files": written, "top_candidates": len(bundle.get("top_candidates") or [])}
