from __future__ import annotations

import asyncio
import json
import pathlib
import time
from collections import Counter

from packages.core.candidate_runtime import CandidateRuntimeOverlayManager
from packages.core.models import AccountState, DecisionRecord, PositionState, Regime, StrategyContext
from packages.core.state_store import EngineStateStore
from packages.data.data_manager import DataManager
from packages.execution.adapters import BinanceRequestError, ExecutionAdapter, format_order
from packages.execution.position_manager import PositionManager
from packages.profiles.symbol_profile import SymbolProfile, SymbolProfileManager
from packages.research.candidate_registry import CandidateRegistry
from packages.research.export_refresh_service import ExportRefreshService
from packages.research.strategy_ideas import StrategyIdeaLibrary
from packages.review.paper_smoke import PaperSmokeWorker
from packages.review.review_queue import ReviewQueue
from packages.risk.engine import RiskEngine
from packages.selector.performance_memory import PerformanceMemory
from packages.selector.regime_engine import RegimeEngine
from packages.selector.strategy_selector import StrategySelector
from packages.strategies.composition import build_strategy_evaluator
from packages.strategies.entry_families import (
    BreakoutRetestEntryFamily,
    EntryFamilyStrategyPlugin,
    FailedBreakoutFadeEntryFamily,
    TrendPullbackEntryFamily,
)
from packages.strategies.range_mr import RangeMR
from packages.strategies.trend_core import TrendCore
from packages.telemetry.audit import AuditStore
from packages.telemetry.logging_utils import log_event, write_status


class MasterEngine:
    def __init__(self, cfg: dict, execution: ExecutionAdapter, export_refresh_service: ExportRefreshService | None = None):
        self.cfg = cfg
        self.execution = execution
        self.state_store = EngineStateStore(cfg.get("state", {}).get("engine_state_file", "runtime/engine_state.json"))
        self.session_info = self.state_store.register_startup()
        self.engine_state = "recovering"
        recovery_cfg = cfg.get("recovery", {})
        self.resume_cooldown_sec = float(recovery_cfg.get("resume_cooldown_sec", 5))
        self.allow_hard_auto_resume = bool(recovery_cfg.get("allow_hard_auto_resume", False))
        self.hard_resume_cooldown_sec = float(recovery_cfg.get("hard_resume_cooldown_sec", 45))
        self.pause_since_ts: float | None = None

        self.data = DataManager(
            cfg["symbols"],
            stale_after_sec=cfg["engine"]["stale_after_sec"],
            require_user_stream_auth=cfg.get("mode") == "live",
        )
        self.risk = RiskEngine(cfg["risk"])
        self.regime = RegimeEngine()
        self.performance_memory = PerformanceMemory(cfg.get("selector", {}).get("performance_memory", {}))
        selector_cfg = cfg.get("selector", {})
        self.selector = StrategySelector(
            selector_cfg["base_edge"],
            performance_memory=self.performance_memory,
            cold_start_bias=selector_cfg.get("family_cold_start_bias", {}),
            cold_start_max_samples=float(selector_cfg.get("family_cold_start_max_samples", 6)),
        )
        self.profile_mgr = SymbolProfileManager(interval_sec=cfg["engine"]["profile_update_sec"])
        self.audit = AuditStore(cfg["telemetry"]["audit_db"])
        self.account = AccountState(
            equity=cfg["account"]["equity"],
            daily_pnl=0.0,
            positions={s: PositionState(symbol=s, qty=0.0, entry_price=0.0) for s in cfg["symbols"]},
            leverage=1.0,
            known=True,
        )
        self.strategies = {
            "TrendCore": TrendCore(),
            "RangeMR": RangeMR(),
            "BreakoutRetest": EntryFamilyStrategyPlugin(
                BreakoutRetestEntryFamily(), {Regime.TREND_UP, Regime.TREND_DOWN, Regime.HIGH_VOL}
            ),
            "TrendPullback": EntryFamilyStrategyPlugin(TrendPullbackEntryFamily(), {Regime.TREND_UP, Regime.TREND_DOWN}),
            "FailedBreakoutFade": EntryFamilyStrategyPlugin(
                FailedBreakoutFadeEntryFamily(), {Regime.RANGE, Regime.HIGH_VOL, Regime.TREND_UP, Regime.TREND_DOWN}
            ),
        }
        self.strategy_evaluator = build_strategy_evaluator(self.strategies)
        self.last_decision: dict | None = None
        self.position_mgr = PositionManager()
        self.current_regimes: dict[str, str] = {}
        self.review_queue = ReviewQueue(cfg.get("review", {}).get("queue_file", "runtime/review_queue.json"))
        self.candidate_registry = CandidateRegistry(cfg.get("review", {}).get("candidate_registry_file", "runtime/candidates_registry.json"))
        self.paper_smoke_worker = PaperSmokeWorker(self.candidate_registry, cfg)
        self.micro_live_cfg = cfg.get("micro_live", {})
        self.paper_candidate_cfg = cfg.get("paper_candidate", {})
        self.active_micro_live: dict[str, dict] = {}
        self.active_paper_candidates: dict[str, dict] = {}
        self.active_live_full: dict[str, dict] = {}
        self.overlay_mgr = CandidateRuntimeOverlayManager(cfg, micro_live_cfg=self.micro_live_cfg, paper_cfg=self.paper_candidate_cfg)
        self.llm_review_history: list[dict] = []
        self.strategy_performance_history: list[dict] = []
        self.paper_trade_history: list[dict] = []
        self.live_trade_history: list[dict] = []
        self.challenger_eval_history: list[dict] = []
        self.review_context: dict = {}
        self.symbol_activity: dict[str, float] = {s: 0.0 for s in cfg["symbols"]}
        self.no_trade_diagnostics = {
            "total_no_trade_events": 0,
            "reason_counts": {},
            "family_reason_counts": {},
            "family_quality": {},
            "recent": [],
        }
        ideas_dir = (cfg.get("bootstrap") or {}).get("strategy_idea_library_dir", "strategy_ideas")
        self.idea_library = StrategyIdeaLibrary(ideas_dir).report()
        self.export_refresh_service = export_refresh_service or ExportRefreshService.from_config(cfg)

        self._load_persistent_state()

    async def run(self) -> None:
        log_event("engine_start", {"mode": self.cfg["mode"], "session": self.session_info.session_id})
        await self._recover_before_trading()
        tasks = [
            asyncio.create_task(self.data.run_market_stream()),
            asyncio.create_task(self.data.run_user_stream()),
            asyncio.create_task(self._decision_loop()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            self._persist_state()
            self.state_store.register_shutdown()

    async def _recover_before_trading(self) -> None:
        self.engine_state = "recovering"
        self.data.load_state(self.cfg.get("state", {}).get("data_state_file", "runtime/data_state.json"))
        self.data.backfill_gap(self.session_info.downtime_sec)
        if self.cfg.get("mode") == "live":
            self.data.reconcile_live_account_state()
        self._sync_account_from_data_state()
        self._recover_candidate_states()
        await asyncio.sleep(float(self.cfg.get("engine", {}).get("recovery_wait_sec", 1.0)))
        self.engine_state = "auto_resumed"

    def _recover_candidate_states(self) -> None:
        rows = self.candidate_registry.list_by_state(["micro_live_active", "micro_live_recovering", "micro_live_paused", "approved_for_live_full", "live_full_active", "paper_candidate_active", "paper_candidate_paused"])
        for row in rows:
            cid = row.get("id")
            if not cid:
                continue
            full = self.candidate_registry.get(cid) or {}
            state = full.get("state")
            if state == "micro_live_active":
                self.candidate_registry.transition(cid, "micro_live_recovering")
            if state in {"micro_live_recovering", "micro_live_paused"} and not full.get("meta", {}).get("manual_review_required", False):
                self.candidate_registry.transition(cid, "micro_live_resumed")
            if state == "live_full_active":
                self.candidate_registry.transition(cid, "approved_for_live_full")
            if state == "paper_candidate_active" and self.cfg.get("mode") == "paper":
                self.candidate_registry.update_meta(cid, meta_patch={"paper_candidate_recovered": True})

    def _can_auto_resume(self, hard_pause: bool = False) -> bool:
        if not self.data.is_healthy() or not self.account.known:
            return False
        if not self.data.stream_health().get("market_fresh", False):
            return False
        if self.session_info.downtime_sec > 0 and self.data.last_update_ts is None:
            return False
        if hard_pause and not self.allow_hard_auto_resume:
            return False
        cooldown = self.hard_resume_cooldown_sec if hard_pause else self.resume_cooldown_sec
        elapsed = time.time() - (self.pause_since_ts or 0)
        return elapsed >= cooldown

    async def _decision_loop(self) -> None:
        while True:
            health_ok = self.data.is_healthy() and self.account.known
            if not health_ok:
                self.engine_state = "soft_paused"
                self.pause_since_ts = self.pause_since_ts or time.time()
                self.risk.trigger_safe_pause()
                for row in self.candidate_registry.list_by_state(["micro_live_active"]):
                    self.candidate_registry.transition(row["id"], "micro_live_paused")
                self._write_status(self.engine_state)
                await asyncio.sleep(1)
                continue

            if self.engine_state == "hard_paused":
                if self._can_auto_resume(hard_pause=True) and self.risk.reduce_only_mode:
                    self.engine_state = "auto_resumed"
                else:
                    self._write_status(self.engine_state)
                    await asyncio.sleep(1)
                    continue

            if self.engine_state in {"soft_paused", "recovering", "auto_resumed"}:
                if self._can_auto_resume():
                    self.risk.clear_safe_pause()
                    self.engine_state = "running" if not self.risk.reduce_only_mode else "auto_resumed"
                    self.pause_since_ts = None
                    for row in self.candidate_registry.list_by_state(["micro_live_paused", "micro_live_recovering"]):
                        self.candidate_registry.transition(row["id"], "micro_live_resumed")
                else:
                    self._write_status(self.engine_state)
                    await asyncio.sleep(1)
                    continue

            self.profile_mgr.maybe_update(self.data.market)
            self._sync_account_from_data_state()
            self._sync_candidate_state_machine()
            self.paper_smoke_worker.process()
            for symbol in self._ordered_symbols():
                snap = self.data.get_snapshot(symbol)
                if not snap:
                    continue
                regime = self.regime.classify(snap)
                self.current_regimes[symbol] = regime.value
                self.position_mgr.on_bar(symbol)
                exit_reason = self.position_mgr.should_exit(symbol, snap)
                if exit_reason:
                    await self._submit_exit(symbol, exit_reason)
                    continue
                runtime_selection = self.overlay_mgr.resolve_runtime(symbol, regime.value, self.cfg.get("mode", "paper"))
                champion = runtime_selection.champion
                spread_cost = (snap.spread_bps / 10000) if snap.spread_bps is not None else (snap.ask - snap.bid) / max(snap.price, 1e-9)
                cost_proxy = {
                    "spread": spread_cost,
                    "slippage": self.profile_mgr.profiles.get(symbol).slippage_proxy if symbol in self.profile_mgr.profiles else 0.0,
                    "funding": self.profile_mgr.profiles.get(symbol).funding_behavior if symbol in self.profile_mgr.profiles else 0.0,
                }
                notional = abs(self.account.positions.get(symbol, PositionState(symbol=symbol)).qty) * snap.price
                exposure_penalty = notional / max(self.account.equity, 1e-9)
                profile = self.profile_mgr.profiles.get(symbol)
                decision = self._build_overlay_decision(
                    champion,
                    symbol,
                    regime,
                    snap,
                    cost_proxy,
                    exposure_penalty,
                    profile,
                )
                if not decision:
                    self._record_no_trade_diagnostics(symbol, regime.value)
                    if champion.blocker:
                        self.last_decision = {
                            "symbol": symbol,
                            "regime": regime.value,
                            "blocked_reason": champion.blocker,
                            "runtime_model": "baseline",
                            "overlay_candidate_id": "",
                        }
                else:
                    self.last_decision = decision.as_audit_payload()
                    await self._execute_decision(decision)
                    self.symbol_activity[symbol] = time.time()

                if self.cfg.get("mode") == "paper":
                    for challenger in runtime_selection.challengers:
                        shadow_decision = self._build_overlay_decision(
                            challenger,
                            symbol,
                            regime,
                            snap,
                            cost_proxy,
                            exposure_penalty,
                            profile,
                        )
                        if shadow_decision:
                            self._record_challenger_signal(challenger, shadow_decision, snap.ts or time.time(), snap.price, cost_proxy)
            self._persist_state()
            self._write_status(self.engine_state)
            self._maybe_refresh_exports_schedule()
            await asyncio.sleep(self.cfg["engine"]["decision_interval_sec"])

    def _runtime_candidate_signature(self) -> dict:
        return {
            "micro_live": sorted((cid, str(row.get("state") or "")) for cid, row in self.active_micro_live.items()),
            "paper_candidates": sorted((cid, str(row.get("state") or "")) for cid, row in self.active_paper_candidates.items()),
            "live_full": sorted((cid, str(row.get("state") or "")) for cid, row in self.active_live_full.items()),
        }

    def _maybe_refresh_exports(self, trigger: str, context: dict | None = None) -> None:
        try:
            self.export_refresh_service.refresh_exports(trigger=trigger, context=context or {})
        except Exception as exc:
            log_event("exports_refresh_failed", {"trigger": trigger, "error": str(exc)})

    def _maybe_refresh_exports_schedule(self) -> None:
        try:
            self.export_refresh_service.maybe_refresh_on_schedule(context={"mode": self.cfg.get("mode")})
        except Exception as exc:
            log_event("exports_refresh_failed", {"trigger": "engine_schedule", "error": str(exc)})

    def _ordered_symbols(self) -> list[str]:
        sched_cfg = self.cfg.get("scheduler", {})
        if not sched_cfg.get("enabled", False):
            return list(self.cfg["symbols"])
        hot_window = float(sched_cfg.get("hot_window_sec", 600))
        now = time.time()
        hot = [s for s in self.cfg["symbols"] if now - self.symbol_activity.get(s, 0.0) <= hot_window]
        cold = [s for s in self.cfg["symbols"] if s not in hot]
        return hot + cold

    def _sync_candidate_state_machine(self) -> None:
        before_signature = self._runtime_candidate_signature()
        self._auto_progress_paper_lifecycle()
        approved_micro = self.candidate_registry.list_by_state(["approved_for_micro_live", "micro_live_recovering", "micro_live_resumed", "micro_live_active"])
        self.active_micro_live = {}
        for row in approved_micro:
            cid = row.get("id")
            if not cid:
                continue
            state = row.get("state")
            symbols = row.get("symbols") or row.get("meta", {}).get("symbols") or []
            self.active_micro_live[cid] = {"symbols": symbols, "state": state, "started_ts": row.get("updated_ts")}
            if state in {"approved_for_micro_live", "micro_live_resumed", "micro_live_recovering"}:
                self.candidate_registry.transition(cid, "micro_live_active")

        self.active_live_full = {}
        for row in self.candidate_registry.list_by_state(["approved_for_live_full", "live_full_active"]):
            cid = row.get("id")
            if not cid:
                continue
            symbols = row.get("symbols") or row.get("meta", {}).get("symbols") or []
            self.active_live_full[cid] = {"symbols": symbols, "state": row.get("state"), "started_ts": row.get("updated_ts")}
            if self.cfg.get("mode") == "live" and row.get("state") == "approved_for_live_full":
                self.candidate_registry.transition(cid, "live_full_active")

        self.active_paper_candidates = {}
        for row in self.candidate_registry.list_by_state(["paper_candidate_active", "paper_candidate_paused", "paper_candidate_winning", "paper_candidate_fading", "challenger_active", "challenger_evaluated"]):
            cid = row.get("id")
            if not cid:
                continue
            symbols = row.get("symbols") or row.get("meta", {}).get("symbols") or []
            self.active_paper_candidates[cid] = {"symbols": symbols, "state": row.get("state"), "started_ts": row.get("updated_ts")}

        runtime_rows = approved_micro + list(self.candidate_registry.list_by_state(["approved_for_live_full", "live_full_active", "paper_candidate_active", "paper_candidate_paused", "paper_candidate_winning", "paper_candidate_fading", "challenger_active", "challenger_evaluated"]))
        self.overlay_mgr.rebuild(runtime_rows, self.cfg.get("mode", "paper"))
        self._evaluate_paper_trade_outcomes()
        evaluated_challengers = self._evaluate_challenger_signals()
        self._evaluate_paper_candidates()
        if evaluated_challengers > 0:
            self._maybe_refresh_exports("challenger_eval", {"evaluated": evaluated_challengers})
        after_signature = self._runtime_candidate_signature()
        if after_signature != before_signature:
            self._maybe_refresh_exports("candidate_change", {"before": before_signature, "after": after_signature})

    def _auto_progress_paper_lifecycle(self) -> None:
        strict_kinds = set(self.cfg.get("incubation", {}).get("strict_candidate_kinds", ["combination_candidate", "new_family_candidate"]))
        strict_hold_sec = float(self.cfg.get("incubation", {}).get("strict_challenger_hold_sec", 120) or 120)
        transitions = [
            ("backtest_pass", "paper_smoke_running", "auto:start_paper_smoke"),
            ("paper_smoke_pass", "challenger_active", "auto:smoke_passed"),
            ("challenger_active", "paper_candidate_active", "auto:challenger_started"),
            ("paper_candidate_pass", "ready_for_review", "auto:paper_candidate_passed"),
        ]
        for src, dst, reason in transitions:
            for row in self.candidate_registry.list_by_state([src]):
                cid = row.get("id")
                if not cid:
                    continue
                kind = row.get("candidate_kind") or row.get("meta", {}).get("candidate_kind", "config_tweak")
                onboarding = row.get("artifacts", {}).get("onboarding_assessment") or row.get("meta", {}).get("onboarding_assessment") or {}
                trust_score = float(onboarding.get("trust_score", row.get("trust_score", 0.5)) or 0.5)
                is_strict = kind in strict_kinds or row.get("track") == "strict"
                if trust_score < float(self.cfg.get("incubation", {}).get("min_trust_for_challenger", 0.28)) and src == "paper_smoke_pass":
                    self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "incubation:low_initial_trust", "review_revalidation_required": True})
                    self.candidate_registry.transition(cid, "needs_revalidation")
                    continue
                if src == "challenger_active" and is_strict:
                    hold_until = float(row.get("meta", {}).get("challenger_hold_until_ts", 0.0) or 0.0)
                    trust_hold_bonus = float(self.cfg.get("incubation", {}).get("trust_hold_sec", 60) or 60) if trust_score < 0.55 else 0.0
                    if hold_until <= 0:
                        self.candidate_registry.update_meta(cid, meta_patch={"challenger_hold_until_ts": time.time() + strict_hold_sec + trust_hold_bonus, "lifecycle_reason": "incubation:strict_challenger_hold"})
                        continue
                    if time.time() < hold_until:
                        continue
                self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": reason})
                if dst == "ready_for_review" and is_strict:
                    self.candidate_registry.transition(cid, "needs_revalidation")
                    self.candidate_registry.update_meta(cid, meta_patch={"review_revalidation_required": True, "lifecycle_reason": "incubation:strict_revalidation_required"})
                    continue
                self.candidate_registry.transition(cid, dst)
                if dst == "ready_for_review":
                    self.candidate_registry.ensure_review_queued(self.review_queue, cid, reason="paper_candidate_pass")

        for row in self.candidate_registry.list_by_state(["needs_revalidation"]):
            cid = row.get("id")
            if not cid:
                continue
            if not row.get("meta", {}).get("review_revalidation_required"):
                continue
            challenger = row.get("artifacts", {}).get("paper_challenger_result", {})
            if float(challenger.get("avg_pnl", -1.0)) < float(self.cfg.get("incubation", {}).get("strict_revalidation_min_avg_pnl", 0.01)):
                continue
            if int(challenger.get("evaluated", 0)) < int(self.cfg.get("incubation", {}).get("strict_revalidation_min_evaluations", 2)):
                continue
            self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "incubation:strict_revalidated", "review_revalidation_required": False})
            self.candidate_registry.transition(cid, "ready_for_review")
            self.candidate_registry.ensure_review_queued(self.review_queue, cid, reason="strict_revalidation_pass")

        for row in self.candidate_registry.list_by_state(["paper_candidate_fail"]):
            cid = row.get("id")
            if not cid:
                continue
            self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "auto:paper_candidate_failed", "runtime_hold": True})
            self.candidate_registry.transition(cid, "needs_revalidation")

        for row in self.candidate_registry.list_by_state(["edge_decay"]):
            cid = row.get("id")
            if not cid:
                continue
            self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "auto:edge_decay_detected", "runtime_hold": True})
            self.candidate_registry.transition(cid, "paper_candidate_paused")
            self.candidate_registry.transition(cid, "needs_revalidation")

    def _build_overlay_decision(self, overlay, symbol: str, regime, snap, cost_proxy: dict, exposure_penalty: float, profile) -> DecisionRecord | None:
        candidates = []
        diagnostics: list[dict] = []
        runtime_profiles = overlay.strategy_profiles
        runtime_configs = overlay.strategy_configs
        for strat_name, config_name in runtime_profiles.get(symbol, {}).get(regime.value, []):
            if strat_name not in self.strategies:
                continue
            cfg_bucket = runtime_configs.get(strat_name, {})
            cfg_row = cfg_bucket.get(config_name)
            if not isinstance(cfg_row, dict):
                continue
            signal, diag = self.strategy_evaluator.evaluate_with_diagnostics(
                strat_name,
                StrategyContext(snapshot=snap, regime=regime, config=cfg_row),
            )
            if isinstance(diag, dict):
                diagnostics.append(
                    {
                        "strategy": strat_name,
                        "config": config_name,
                        "reason": diag.get("reason", "unknown"),
                        "entry_family": diag.get("entry_family", strat_name),
                        "filter_pack": diag.get("filter_pack"),
                        "exit_pack": diag.get("exit_pack"),
                        "setup_quality": float(diag.get("setup_quality", 0.0) or 0.0),
                    }
                )
            if signal:
                candidates.append((strat_name, config_name, signal))
        self._last_setup_diagnostics = diagnostics
        decision = self.selector.select(
            symbol,
            regime,
            candidates,
            cost_proxy,
            exposure_penalty=exposure_penalty,
            symbol_profile=profile,
            current_positions={s: p.qty for s, p in self.account.positions.items()},
        )
        if not decision:
            return None
        decision.runtime_model = overlay.runtime_model
        decision.overlay_candidate_id = overlay.candidate_id or ""
        return decision

    def _record_no_trade_diagnostics(self, symbol: str, regime: str) -> None:
        rows = list(getattr(self, "_last_setup_diagnostics", []) or [])
        if not rows:
            return
        reason_counter = Counter(str(r.get("reason") or "unknown") for r in rows)
        primary_reason, _ = reason_counter.most_common(1)[0]
        self.no_trade_diagnostics["total_no_trade_events"] = int(self.no_trade_diagnostics.get("total_no_trade_events", 0)) + 1
        reason_counts = self.no_trade_diagnostics.setdefault("reason_counts", {})
        reason_counts[primary_reason] = int(reason_counts.get(primary_reason, 0)) + 1

        family_reason = self.no_trade_diagnostics.setdefault("family_reason_counts", {})
        family_quality = self.no_trade_diagnostics.setdefault("family_quality", {})
        for row in rows:
            family = str(row.get("entry_family") or row.get("strategy") or "unknown")
            reason = str(row.get("reason") or "unknown")
            family_bucket = family_reason.setdefault(family, {})
            family_bucket[reason] = int(family_bucket.get(reason, 0)) + 1

            quality = family_quality.setdefault(family, {"observed": 0, "setup_quality_sum": 0.0})
            quality["observed"] = int(quality.get("observed", 0)) + 1
            quality["setup_quality_sum"] = float(quality.get("setup_quality_sum", 0.0)) + float(row.get("setup_quality", 0.0) or 0.0)

        recent = self.no_trade_diagnostics.setdefault("recent", [])
        recent.append({"ts": time.time(), "symbol": symbol, "regime": regime, "primary_reason": primary_reason, "families": sorted({r.get("entry_family") for r in rows if r.get("entry_family")})})
        self.no_trade_diagnostics["recent"] = recent[-50:]

    def _record_challenger_signal(self, challenger, decision: DecisionRecord, signal_ts: float, entry_basis: float, cost_proxy: dict) -> None:
        qty = max(0.0, self.cfg["sizing"]["base_qty"] * float(decision.sizing.get("confidence", 0.0)))
        challenger_cfg = self.paper_candidate_cfg or {}
        fee_rate = float(challenger_cfg.get("fee_rate", 0.0006) or 0.0006)
        slippage_multiplier = float(challenger_cfg.get("slippage_multiplier", 1.0) or 1.0)
        funding_rate_8h = float(challenger_cfg.get("funding_rate_8h", 0.0001) or 0.0001)
        candidate_row = self.candidate_registry.get(challenger.candidate_id or "") if challenger.candidate_id else None
        exit_pack = (
            (candidate_row or {}).get("artifacts", {}).get("strategy_composition", {}).get("exit_pack")
            or (candidate_row or {}).get("meta", {}).get("strategy_composition", {}).get("exit_pack")
            or "passthrough"
        )
        self.challenger_eval_history.append(
            {
                "symbol": decision.symbol,
                "regime": decision.regime,
                "strategy": decision.selected_strategy,
                "config": decision.selected_config,
                "side": decision.selected_side,
                "signal_ts": signal_ts,
                "runtime_model": challenger.runtime_model,
                "overlay_candidate_id": challenger.candidate_id or "",
                "exit_pack": exit_pack,
                "hypothetical_qty": qty,
                "entry_basis": entry_basis,
                "fee_rate": fee_rate,
                "slippage_rate": max(0.0, float(cost_proxy.get("slippage", 0.0) or 0.0) * slippage_multiplier),
                "funding_rate_8h": funding_rate_8h,
                "window_sec": float(self.paper_candidate_cfg.get("compare_window_sec", self.paper_candidate_cfg.get("window_sec", 300)) or 300),
                "status": "pending",
                "result_pnl": None,
                "result_cost_adjusted_pnl": None,
                "result_ts": None,
            }
        )

    def _challenger_window_extrema(self, symbol: str, signal_ts: float, fallback_price: float) -> tuple[float, float, int]:
        candles = list(self.data.candles.get(symbol, {}).get("1h", []))
        if not candles:
            return fallback_price, fallback_price, 0
        window_ms = signal_ts * 1000
        highs = []
        lows = []
        for candle in candles:
            close_time = float(candle.get("close_time", 0.0) or 0.0)
            if close_time <= 0 or close_time < window_ms:
                continue
            highs.append(float(candle.get("high", fallback_price) or fallback_price))
            lows.append(float(candle.get("low", fallback_price) or fallback_price))
        if not highs or not lows:
            return fallback_price, fallback_price, 0
        return max(highs), min(lows), len(highs)

    def _shadow_truth_v2_classification(self, row: dict, pnl: float, cost_adjusted_pnl: float, mfe: float, mae: float, total_cost: float) -> dict:
        move_quality = 0.0 if (mfe + mae) <= 1e-9 else max(0.0, min(1.0, (mfe - mae) / max(mfe + mae, 1e-9)))
        entry_quality = 0.0 if (mfe + mae) <= 1e-9 else max(0.0, min(1.0, mfe / max(mfe + mae, 1e-9)))
        capture_ratio = 0.0 if mfe <= 1e-9 else max(0.0, min(1.0, max(0.0, pnl) / mfe))
        timing_quality = max(0.0, min(1.0, capture_ratio * 0.6 + move_quality * 0.4))
        cost_quality = max(0.0, min(1.0, 1.0 - (total_cost / max(abs(pnl) + total_cost, 1e-9))))
        path_quality = max(0.0, min(1.0, move_quality * 0.55 + entry_quality * 0.45))

        exit_pack = str(row.get("exit_pack") or "passthrough")
        expected_capture = {
            "passthrough": 0.2,
            "atr_trail": 0.35,
            "fixed_rr": 0.5,
        }.get(exit_pack, 0.3)
        exit_quality = max(0.0, min(1.0, capture_ratio / max(expected_capture, 1e-9)))
        if pnl < 0 and mfe > 0:
            exit_quality = max(0.0, exit_quality - 0.3)

        classification = "mixed_outcome"
        if cost_adjusted_pnl < 0 and pnl > 0:
            classification = "edge_died_in_costs"
        elif mfe <= 1e-9 and abs(pnl) <= 1e-9:
            classification = "signal_not_tradeable"
        elif entry_quality < 0.4 and mae > mfe:
            classification = "poor_entry"
        elif entry_quality >= 0.55 and exit_quality < 0.35 and mfe > 0:
            classification = "good_entry_bad_exit"
        elif entry_quality >= 0.55 and timing_quality < 0.4:
            classification = "good_idea_bad_timing"
        elif pnl > 0 and path_quality < 0.4:
            classification = "good_move_slow_follow_through"
        elif cost_adjusted_pnl > 0 and path_quality > 0.55 and cost_quality > 0.45:
            classification = "robust_shadow_win"

        return {
            "entry_quality": entry_quality,
            "exit_quality": exit_quality,
            "exit_pack_quality": exit_quality,
            "timing_quality": timing_quality,
            "cost_quality": cost_quality,
            "path_quality": path_quality,
            "move_quality": move_quality,
            "outcome_classification": classification,
        }

    def _evaluate_challenger_signals(self) -> int:
        if self.cfg.get("mode") != "paper":
            return 0
        now = time.time()
        evaluated = 0
        for row in self.challenger_eval_history:
            if row.get("status") != "pending":
                continue
            signal_ts = float(row.get("signal_ts") or 0.0)
            window_sec = float(row.get("window_sec") or 0.0)
            if signal_ts <= 0 or (now - signal_ts) < window_sec:
                continue
            snap = self.data.get_snapshot(row.get("symbol", ""))
            if not snap:
                continue
            entry = float(row.get("entry_basis") or 0.0)
            qty = float(row.get("hypothetical_qty") or 0.0)
            side = row.get("side")
            max_price, min_price, window_candles = self._challenger_window_extrema(str(row.get("symbol") or ""), signal_ts, snap.price)
            if side == "BUY":
                pnl = (snap.price - entry) * qty
                mfe = max(0.0, (max_price - entry) * qty)
                mae = max(0.0, (entry - min_price) * qty)
            else:
                pnl = (entry - snap.price) * qty
                mfe = max(0.0, (entry - min_price) * qty)
                mae = max(0.0, (max_price - entry) * qty)

            notional = abs(entry * qty)
            fee_cost = notional * max(0.0, float(row.get("fee_rate") or 0.0))
            slippage_cost = notional * max(0.0, float(row.get("slippage_rate") or 0.0))
            funding_rate_8h = max(0.0, float(row.get("funding_rate_8h") or 0.0))
            funding_cost = notional * funding_rate_8h * max(window_sec, 0.0) / (8 * 3600)
            total_cost = fee_cost + slippage_cost + funding_cost
            cost_adjusted_pnl = pnl - total_cost
            quality = self._shadow_truth_v2_classification(row, pnl, cost_adjusted_pnl, mfe, mae, total_cost)

            row["status"] = "evaluated"
            row["result_pnl"] = pnl
            row["result_cost_adjusted_pnl"] = cost_adjusted_pnl
            row["result_ts"] = now
            row["mfe"] = mfe
            row["mae"] = mae
            row.update(quality)
            row["shadow_truth_v2"] = {
                "entry_quality": round(float(quality["entry_quality"]), 6),
                "exit_quality": round(float(quality["exit_quality"]), 6),
                "timing_quality": round(float(quality["timing_quality"]), 6),
                "cost_quality": round(float(quality["cost_quality"]), 6),
                "path_quality": round(float(quality["path_quality"]), 6),
                "outcome_classification": quality["outcome_classification"],
            }
            row["cost_breakdown"] = {
                "notional": round(notional, 8),
                "fee_cost": round(fee_cost, 8),
                "slippage_cost": round(slippage_cost, 8),
                "funding_cost": round(funding_cost, 8),
                "total_cost": round(total_cost, 8),
            }
            row["window_candles"] = window_candles
            baseline_scale = max(abs(entry * qty * 0.001), 1e-6)
            challenger_relative = max(-1.0, min(1.0, cost_adjusted_pnl / baseline_scale))
            row["challenger_relative"] = challenger_relative
            evaluated += 1
            self.performance_memory.update(
                symbol=str(row.get("symbol") or ""),
                regime=str(row.get("regime") or ""),
                strategy=str(row.get("strategy") or ""),
                config=str(row.get("config") or ""),
                pnl=cost_adjusted_pnl,
                source="challenger",
                ts=now,
                challenger_relative=challenger_relative,
            )
        self.challenger_eval_history = self.challenger_eval_history[-1000:]
        return evaluated

    def _evaluate_paper_trade_outcomes(self) -> None:
        if self.cfg.get("mode") != "paper":
            return
        now = time.time()
        for row in self.paper_trade_history:
            if row.get("status") != "pending":
                continue
            opened_ts = float(row.get("opened_ts") or 0.0)
            window_sec = float(row.get("window_sec") or self.performance_memory.paper_window_sec)
            if opened_ts <= 0 or now - opened_ts < window_sec:
                continue
            symbol = str(row.get("symbol") or "")
            snap = self.data.get_snapshot(symbol)
            if not snap:
                continue
            side = row.get("side")
            entry = float(row.get("entry_basis") or 0.0)
            qty = float(row.get("qty") or 0.0)
            pnl = (snap.price - entry) * qty if side == "BUY" else (entry - snap.price) * qty
            row["status"] = "evaluated"
            row["result_pnl"] = pnl
            row["result_ts"] = now
            self.performance_memory.update(
                symbol=symbol,
                regime=str(row.get("regime") or ""),
                strategy=str(row.get("strategy") or ""),
                config=str(row.get("config") or ""),
                pnl=pnl,
                source="paper",
                ts=now,
            )
        self.paper_trade_history = self.paper_trade_history[-500:]

    def _micro_live_context_for_symbol(self, symbol: str) -> dict | None:
        cids = [cid for cid in self.overlay_mgr.status().get("by_symbol", {}).get(symbol, []) if self.overlay_mgr.active.get(cid, {}).get("lane") == "micro_live"]
        if not cids and self.active_micro_live:
            for cid, row in self.active_micro_live.items():
                symbols = row.get("symbols") or []
                if not symbols or symbol in symbols or symbols == ["MULTI"]:
                    cids.append(cid)
        if not cids:
            return None
        if self.micro_live_cfg.get("max_symbols", 0) == 1:
            scoped = set()
            source = self.active_micro_live or {cid: self.overlay_mgr.active.get(cid, {}) for cid in cids}
            for row in source.values():
                for sym in (row.get("symbols") or [symbol]):
                    if sym != "MULTI":
                        scoped.add(sym)
            if len(scoped) > 1:
                return {"blocked": True, "reason": "micro_live_one_symbol_only", "candidates": cids}
        return {"blocked": False, "candidates": cids}

    def _evaluate_paper_candidates(self) -> None:
        if self.cfg.get("mode") != "paper":
            return
        window_sec = float(self.paper_candidate_cfg.get("window_sec", 300) or 300)
        min_trades = int(self.paper_candidate_cfg.get("min_trades", 1) or 1)
        winning_avg_pnl = float(self.paper_candidate_cfg.get("winning_avg_pnl", 0.0) or 0.0)
        fade_avg_pnl = float(self.paper_candidate_cfg.get("fade_avg_pnl", -0.01) or -0.01)
        edge_decay_avg_pnl = float(self.paper_candidate_cfg.get("edge_decay_avg_pnl", -0.05) or -0.05)
        max_negative_ratio = float(self.paper_candidate_cfg.get("max_negative_ratio", 0.7) or 0.7)
        strict_kinds = set(self.cfg.get("incubation", {}).get("strict_candidate_kinds", ["combination_candidate", "new_family_candidate"]))
        now = time.time()
        for cid, row in self.active_paper_candidates.items():
            if row.get("state") not in {"paper_candidate_active", "paper_candidate_winning", "paper_candidate_fading", "challenger_active", "challenger_evaluated"}:
                continue
            started = float(row.get("started_ts") or now)
            if now - started < window_sec:
                continue
            evaluations = [
                x for x in self.challenger_eval_history
                if x.get("overlay_candidate_id") == cid
                and x.get("status") == "evaluated"
                and now - float(x.get("result_ts", 0)) <= window_sec
            ]
            avg_pnl = (sum(float(x.get("result_pnl") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_cost_adjusted_pnl = (
                sum(float(x.get("result_cost_adjusted_pnl") or x.get("result_pnl") or 0.0) for x in evaluations) / len(evaluations)
                if evaluations
                else 0.0
            )
            avg_mfe = (sum(float(x.get("mfe") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_mae = (sum(float(x.get("mae") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_move_quality = (sum(float(x.get("move_quality") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_entry_quality = (sum(float(x.get("entry_quality") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_exit_pack_quality = (sum(float(x.get("exit_pack_quality") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_exit_quality = (sum(float(x.get("exit_quality") or x.get("exit_pack_quality") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_timing_quality = (sum(float(x.get("timing_quality") or x.get("move_quality") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            avg_cost_quality = (
                sum(
                    float(
                        x.get("cost_quality")
                        if x.get("cost_quality") is not None
                        else (1.0 if float(x.get("result_cost_adjusted_pnl") or x.get("result_pnl") or 0.0) > 0 else 0.5)
                    )
                    for x in evaluations
                )
                / len(evaluations)
            ) if evaluations else 0.0
            avg_path_quality = (sum(float(x.get("path_quality") or x.get("move_quality") or 0.0) for x in evaluations) / len(evaluations)) if evaluations else 0.0
            outcome_counts = Counter(str(x.get("outcome_classification") or "unknown") for x in evaluations)
            dominant_outcome = outcome_counts.most_common(1)[0][0] if outcome_counts else "unknown"
            negative_ratio = (
                sum(1 for x in evaluations if float(x.get("result_cost_adjusted_pnl") or x.get("result_pnl") or 0.0) < 0) / len(evaluations)
                if evaluations
                else 1.0
            )
            candidate_row = self.candidate_registry.get(cid) or {}
            kind = candidate_row.get("candidate_kind") or candidate_row.get("meta", {}).get("candidate_kind", "config_tweak")
            onboarding = candidate_row.get("artifacts", {}).get("onboarding_assessment") or candidate_row.get("meta", {}).get("onboarding_assessment") or {}
            trust_score = float(onboarding.get("trust_score", candidate_row.get("trust_score", 0.5)) or 0.5)
            required_min_trades = min_trades
            required_winning_avg_pnl = winning_avg_pnl
            if trust_score < 0.5:
                required_min_trades += 1
            if kind in strict_kinds:
                required_min_trades = max(min_trades, int(self.cfg.get("incubation", {}).get("strict_min_trades", min_trades + 1)))
                required_winning_avg_pnl = max(winning_avg_pnl, float(self.cfg.get("incubation", {}).get("strict_winning_avg_pnl", winning_avg_pnl + 0.01)))
            self.candidate_registry.transition(cid, "challenger_evaluated")
            self.candidate_registry.update_meta(
                cid,
                artifacts_patch={
                    "paper_challenger_result": {
                        "evaluated": len(evaluations),
                        "avg_pnl": avg_pnl,
                        "avg_cost_adjusted_pnl": avg_cost_adjusted_pnl,
                        "negative_ratio": negative_ratio,
                        "avg_mfe": avg_mfe,
                        "avg_mae": avg_mae,
                        "avg_move_quality": avg_move_quality,
                        "avg_entry_quality": avg_entry_quality,
                        "avg_exit_pack_quality": avg_exit_pack_quality,
                        "avg_exit_quality": avg_exit_quality,
                        "avg_timing_quality": avg_timing_quality,
                        "avg_cost_quality": avg_cost_quality,
                        "avg_path_quality": avg_path_quality,
                        "outcome_classification_counts": dict(outcome_counts),
                        "dominant_outcome_classification": dominant_outcome,
                        "window_sec": window_sec,
                        "ts": now,
                    }
                },
            )
            if len(evaluations) < required_min_trades:
                self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "paper:no_signal_density"})
                self.candidate_registry.transition(cid, "paper_candidate_fail")
                continue
            if dominant_outcome in {"edge_died_in_costs", "signal_not_tradeable"} or avg_cost_quality < 0.3:
                self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "paper:cost_or_tradeability_decay"})
                self.candidate_registry.transition(cid, "paper_candidate_fading")
                self.candidate_registry.transition(cid, "edge_decay")
                continue
            if dominant_outcome == "poor_entry" and avg_entry_quality < 0.35:
                self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "paper:entry_quality_failure"})
                self.candidate_registry.transition(cid, "paper_candidate_fail")
                continue
            if avg_cost_adjusted_pnl <= edge_decay_avg_pnl or negative_ratio > max_negative_ratio:
                self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "paper:edge_decay"})
                self.candidate_registry.transition(cid, "paper_candidate_fading")
                self.candidate_registry.transition(cid, "edge_decay")
                continue
            if avg_cost_adjusted_pnl <= fade_avg_pnl:
                self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "paper:fading_momentum"})
                self.candidate_registry.transition(cid, "paper_candidate_fading")
                continue
            if avg_cost_adjusted_pnl >= required_winning_avg_pnl:
                self.candidate_registry.update_meta(cid, meta_patch={"lifecycle_reason": "paper:winning"})
                self.candidate_registry.transition(cid, "paper_candidate_winning")
                self.candidate_registry.transition(cid, "paper_candidate_pass")

    async def _execute_decision(self, decision: DecisionRecord) -> None:
        side = decision.selected_side
        micro_ctx = self._micro_live_context_for_symbol(decision.symbol)
        risk_mult = float(self.micro_live_cfg.get("risk_multiplier", 1.0)) if micro_ctx and not micro_ctx.get("blocked") else 1.0
        qty = max(0.0, self.cfg["sizing"]["base_qty"] * decision.sizing["confidence"] * risk_mult)
        decision.side = side
        decision.qty = qty
        order = format_order(decision.symbol, side, qty)
        rr = self.risk.evaluate_order(order, self.account, self.data.market)
        if micro_ctx and rr.allowed:
            micro_cap = float(self.micro_live_cfg.get("max_total_exposure_notional", 0) or 0)
            if micro_cap > 0 and self.risk._exposure(self.account, self.data.market) > micro_cap:
                rr.allowed = False
                rr.reason = "micro_live_total_exposure_cap"
        decision.caps_status = {
            "safe_pause": self.risk.safe_pause,
            "reduce_only_mode": self.risk.reduce_only_mode,
            "risk_result": rr.reason,
            "micro_live": micro_ctx or {},
            "runtime_model": decision.runtime_model,
            "overlay_candidate_id": decision.overlay_candidate_id,
        }
        if micro_ctx and micro_ctx.get("blocked"):
            rr.allowed = False
            rr.reason = micro_ctx.get("reason", "micro_live_blocked")
        if not rr.allowed:
            decision.blocked_reason = rr.reason
            self.audit.save_decision(decision)
            log_event("decision_blocked", decision.as_audit_payload())
            if rr.reason in {"kill_switch_triggered", "weekly_guard_triggered"}:
                self.engine_state = "hard_paused"
                self.pause_since_ts = self.pause_since_ts or time.time()
                await self.risk.panic_flatten(self.account, self.execution)
            return
        order.reduce_only = rr.reduce_only
        try:
            res = await self.execution.place_order(order)
        except BinanceRequestError as exc:
            if exc.category in {"auth", "rate_limit", "server", "timeout", "network"}:
                self.risk.trigger_safe_pause(reduce_only=True)
                self.pause_since_ts = self.pause_since_ts or time.time()
                self.engine_state = "soft_paused"
            decision.blocked_reason = f"execution_error:{exc.category}"
            self.audit.save_decision(decision)
            return
        self.audit.save_decision(decision)
        payload = decision.as_audit_payload()
        snap = self.data.get_snapshot(decision.symbol)
        trade_row = {
            "ts": time.time(),
            "symbol": decision.symbol,
            "side": side,
            "qty": qty,
            "mode": self.cfg.get("mode"),
            "micro_live": bool(micro_ctx),
            "runtime_model": decision.runtime_model,
            "overlay_candidate_id": decision.overlay_candidate_id,
        }
        if self.cfg.get("mode") == "paper":
            trade_row.update(
                {
                    "strategy": decision.selected_strategy,
                    "config": decision.selected_config,
                    "regime": decision.regime,
                    "entry_basis": snap.price if snap else 0.0,
                    "opened_ts": time.time(),
                    "window_sec": self.performance_memory.paper_window_sec,
                    "status": "pending",
                    "result_pnl": None,
                    "result_ts": None,
                }
            )
            self.paper_trade_history.append(trade_row)
        else:
            self.live_trade_history.append(trade_row)
        self.strategy_performance_history.append({"ts": time.time(), "symbol": decision.symbol, "strategy": decision.selected_strategy, "config": decision.selected_config, "qty": qty, "side": side, "blocked": False, "runtime_model": decision.runtime_model, "overlay_candidate_id": decision.overlay_candidate_id})
        payload["caps_status"]["reduce_only_order"] = order.reduce_only
        payload["result"] = res
        log_event("order_submitted", payload)
        fill_price = self.data.get_snapshot(decision.symbol).price if self.data.get_snapshot(decision.symbol) else 0.0
        if self.cfg.get("mode") == "paper":
            self.data.apply_paper_fill(decision.symbol, side, qty, fill_price, reduce_only=order.reduce_only)
            self._sync_account_from_data_state()
            self.position_mgr.on_entry(
                decision.symbol,
                side,
                qty,
                fill_price,
                {
                    "stop_price": decision.sizing.get("stop_price"),
                    "take_profit": decision.sizing.get("take_profit"),
                    "time_stop_bars": decision.sizing.get("time_stop_bars", 0),
                    "trail_mult": decision.sizing.get("trail_mult", 1.5),
                    "exit_pack": decision.sizing.get("exit_pack", "passthrough"),
                    "partial_take_profit": decision.sizing.get("partial_take_profit"),
                    "partial_fraction": decision.sizing.get("partial_fraction", 0.0),
                },
            )

    async def _submit_exit(self, symbol: str, reason: str) -> None:
        pos = self.account.positions.get(symbol)
        if not pos or abs(pos.qty) <= 0:
            self.position_mgr.clear(symbol)
            return
        side = "SELL" if pos.qty > 0 else "BUY"
        qty = abs(pos.qty)
        if reason == "partial_take_profit":
            partial_fraction = float(self.position_mgr.state.get(symbol, {}).get("partial_fraction", 0.5))
            reduced_qty = self.position_mgr.reduce_position(symbol, partial_fraction)
            qty = min(qty, max(0.0, reduced_qty))
            if qty <= 0:
                return
        order = format_order(symbol, side, qty, reduce_only=True)
        rr = self.risk.evaluate_order(order, self.account, self.data.market)
        if not rr.allowed:
            return
        await self.execution.place_order(order)
        fill_price = self.data.get_snapshot(symbol).price if self.data.get_snapshot(symbol) else pos.entry_price
        if self.cfg.get("mode") == "paper":
            self.data.apply_paper_fill(symbol, side, qty, fill_price, reduce_only=True)
            self._sync_account_from_data_state()
        if reason != "partial_take_profit" or abs(self.account.positions.get(symbol, PositionState(symbol=symbol)).qty) <= 0:
            self.position_mgr.clear(symbol)

    def _sync_account_from_data_state(self) -> None:
        if self.data.account_state.get("equity") is not None:
            self.account.equity = float(self.data.account_state["equity"])
            self.account.known = True
        else:
            self.account.known = self.cfg.get("mode") != "live"
        known_positions = self.data.account_state.get("positions", {})
        for sym in self.cfg["symbols"]:
            row = known_positions.get(sym, {"qty": 0.0, "entry_price": 0.0})
            self.account.positions[sym] = PositionState(symbol=sym, qty=float(row.get("qty", 0.0)), entry_price=float(row.get("entry_price", 0.0)))
        last_event_ts = self.data.account_state.get("last_event_ts")
        if self.cfg.get("mode") == "live":
            self.account.known = bool(last_event_ts and (time.time() - float(last_event_ts)) <= (self.cfg["engine"]["stale_after_sec"] * 2))

    def _load_persistent_state(self) -> None:
        payload = self.state_store.load()
        self.position_mgr.state = payload.get("position_manager_state", {})
        self.risk.import_state(payload.get("risk_state", {}))
        for sym, raw in payload.get("symbol_profiles", {}).items():
            self.profile_mgr.profiles[sym] = SymbolProfile(**raw)
        self.llm_review_history = payload.get("llm_review_history", [])[-200:]
        self.strategy_performance_history = payload.get("strategy_performance_history", [])[-500:]
        self.paper_trade_history = payload.get("paper_trade_history", [])[-500:]
        self.live_trade_history = payload.get("live_trade_history", [])[-500:]
        self.challenger_eval_history = payload.get("challenger_eval_history", [])[-1000:]
        self.performance_memory.import_state(payload.get("performance_memory_state", {}))
        self.review_context = payload.get("review_context", {})
        self.no_trade_diagnostics = payload.get("no_trade_diagnostics", self.no_trade_diagnostics)
        self.active_micro_live = payload.get("micro_live_active", {})
        self.active_paper_candidates = payload.get("paper_candidate_active", {})
        self.active_live_full = payload.get("live_full_active", {})

    def _persist_state(self) -> None:
        payload = self.state_store.load()
        payload["engine_state"] = self.engine_state
        payload["position_manager_state"] = self.position_mgr.state
        payload["risk_state"] = self.risk.export_state()
        payload["symbol_profiles"] = {k: vars(v) for k, v in self.profile_mgr.profiles.items()}
        payload["candidate_registry_snapshot"] = self.candidate_registry.report()
        payload["review_queue"] = self.review_queue.list_ready()
        payload["llm_review_history"] = self.llm_review_history[-200:]
        payload["strategy_performance_history"] = self.strategy_performance_history[-500:]
        payload["paper_trade_history"] = self.paper_trade_history[-500:]
        payload["live_trade_history"] = self.live_trade_history[-500:]
        payload["challenger_eval_history"] = self.challenger_eval_history[-1000:]
        payload["performance_memory_state"] = self.performance_memory.export_state()
        payload["review_context"] = self.review_context
        payload["no_trade_diagnostics"] = self.no_trade_diagnostics
        payload["micro_live_active"] = self.active_micro_live
        payload["paper_candidate_active"] = self.active_paper_candidates
        payload["live_full_active"] = self.active_live_full
        payload["runtime_overlay_status"] = self.overlay_mgr.status()
        self.state_store.save(payload)
        self.data.persist_state(self.cfg.get("state", {}).get("data_state_file", "runtime/data_state.json"))

    def _write_status(self, state: str) -> None:
        llm_cfg = self.cfg.get("llm_research") or self.cfg.get("llm", {})
        budget_path = pathlib.Path(llm_cfg.get("budget_file", "runtime/llm_budget.json"))
        budget_history = json.loads(budget_path.read_text(encoding="utf-8")).get("calls", []) if budget_path.exists() else []
        now = time.time()
        budget_runtime = {
            "used_day": sum(1 for row in budget_history if now - float(row.get("ts", 0)) <= 86400),
            "used_week": sum(1 for row in budget_history if now - float(row.get("ts", 0)) <= 7 * 86400),
        }
        write_status(
            self.cfg["telemetry"]["status_file"],
            {
                "state": state,
                "mode": self.cfg["mode"],
                "symbols": self.cfg["symbols"],
                "recovery_state": {
                    "session_id": self.session_info.session_id,
                    "downtime_sec": self.session_info.downtime_sec,
                    "pause_since_ts": self.pause_since_ts,
                },
                "open_positions": {
                    sym: {"qty": pos.qty, "entry_price": pos.entry_price}
                    for sym, pos in self.account.positions.items()
                    if abs(pos.qty) > 0
                },
                "last_decision": self.last_decision,
                "no_trade_diagnostics": self.no_trade_diagnostics,
                "ws_status": self.data.stream_health(),
                "account_sync_health": {
                    "known": self.account.known,
                    "last_event_age_sec": self.data.stream_health().get("account_last_event_age_sec"),
                },
                "current_regime": self.current_regimes,
                "market_features": {
                    sym: {
                        "price": snap.price,
                        "atr": snap.atr,
                        "rsi": snap.rsi,
                        "trend_slope": snap.trend_slope,
                        "realized_volatility": snap.realized_volatility,
                        "spread_bps": snap.spread_bps,
                        "atr_pct_of_price": snap.atr_pct_of_price,
                        "session_bucket": snap.session_bucket,
                        "hour_bucket": snap.hour_bucket,
                        "range_compression_score": snap.range_compression_score,
                        "breakout_distance_from_recent_range": snap.breakout_distance_from_recent_range,
                        "rsi_1h": snap.rsi_1h,
                        "rsi_4h": snap.rsi_4h,
                        "atr_1h": snap.atr_1h,
                        "atr_4h": snap.atr_4h,
                    }
                    for sym, snap in self.data.market.items()
                },
                "safe_pause": self.risk.safe_pause,
                "reduce_only": self.risk.reduce_only_mode,
                "candidate_registry": self.candidate_registry.report(),
                "review_queue_size": len(self.review_queue.list_ready()),
                "llm_status": {
                    "provider": llm_cfg.get("provider"),
                    "fallback": llm_cfg.get("fallback_provider"),
                    "enabled": llm_cfg.get("enabled", False),
                    "workflow": "manual_exports" if not llm_cfg.get("enabled", False) else "internal_api_optional",
                    "manual_prompt_file": "runtime/llm_exports/paste_to_llm.md",
                    "budget_limits": llm_cfg.get("budgets", {}),
                    "budget_usage": budget_runtime,
                },
                "micro_live": {"enabled": self.micro_live_cfg.get("enabled", False), "active": self.active_micro_live},
                "paper_candidate": {"active": self.active_paper_candidates, "config": self.paper_candidate_cfg, "challenger_evaluations": self.challenger_eval_history[-50:]},
                "live_full": {"active": self.active_live_full},
                "runtime_overlays": self.overlay_mgr.status(),
                "bootstrap": {
                    "idea_library_total": self.idea_library.get("total", 0),
                    "implemented_plugins": [x.get("family") for x in self.idea_library.get("implemented_plugins", [])],
                    "strict_track_ideas": [x.get("id") for x in self.idea_library.get("strict_track_candidates", [])[:6]],
                },
                "last_review_result_location": "runtime/reviews",
                "risk_caps_status": {
                    "daily_pnl": self.account.daily_pnl,
                    "daily_loss_cap": self.cfg["risk"]["max_daily_loss"],
                    "weekly_loss_cap": self.cfg["risk"].get("max_weekly_loss"),
                    "drawdown_cap_pct": self.cfg["risk"].get("max_drawdown_pct"),
                    "total_exposure_notional": self.risk._exposure(self.account, self.data.market),
                    "total_exposure_cap": self.cfg["risk"]["max_total_exposure_notional"],
                    "leverage": self.account.leverage,
                    "max_leverage": self.cfg["risk"]["max_leverage"],
                },
                "ts": time.time(),
            },
        )
