from __future__ import annotations

import asyncio
import time

from packages.core.models import AccountState, DecisionRecord, PositionState
from packages.core.state_store import EngineStateStore
from packages.data.data_manager import DataManager
from packages.execution.adapters import BinanceRequestError, ExecutionAdapter, format_order
from packages.execution.position_manager import PositionManager
from packages.profiles.symbol_profile import SymbolProfileManager
from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ReviewQueue
from packages.risk.engine import RiskEngine
from packages.selector.regime_engine import RegimeEngine
from packages.selector.strategy_selector import StrategySelector
from packages.strategies.range_mr import RangeMR
from packages.strategies.trend_core import TrendCore
from packages.telemetry.audit import AuditStore
from packages.telemetry.logging_utils import log_event, write_status


class MasterEngine:
    def __init__(self, cfg: dict, execution: ExecutionAdapter):
        self.cfg = cfg
        self.execution = execution
        self.state_store = EngineStateStore(cfg.get("state", {}).get("engine_state_file", "runtime/engine_state.json"))
        self.session_info = self.state_store.register_startup()
        self.engine_state = "recovering"

        self.data = DataManager(
            cfg["symbols"],
            stale_after_sec=cfg["engine"]["stale_after_sec"],
            require_user_stream_auth=cfg.get("mode") == "live",
        )
        self.risk = RiskEngine(cfg["risk"])
        self.regime = RegimeEngine()
        self.selector = StrategySelector(cfg["selector"]["base_edge"])
        self.profile_mgr = SymbolProfileManager(interval_sec=cfg["engine"]["profile_update_sec"])
        self.audit = AuditStore(cfg["telemetry"]["audit_db"])
        self.account = AccountState(
            equity=cfg["account"]["equity"],
            daily_pnl=0.0,
            positions={s: PositionState(symbol=s, qty=0.0, entry_price=0.0) for s in cfg["symbols"]},
            leverage=1.0,
            known=True,
        )
        self.strategies = {"TrendCore": TrendCore(), "RangeMR": RangeMR()}
        self.last_decision: dict | None = None
        self.position_mgr = PositionManager()
        self.current_regimes: dict[str, str] = {}
        self.review_queue = ReviewQueue(cfg.get("review", {}).get("queue_file", "runtime/review_queue.json"))
        self.candidate_registry = CandidateRegistry(cfg.get("review", {}).get("candidate_registry_file", "runtime/candidates_registry.json"))

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
            self._sync_account_from_data_state()
        await asyncio.sleep(float(self.cfg.get("engine", {}).get("recovery_wait_sec", 1.0)))
        self.engine_state = "auto_resumed"

    async def _decision_loop(self) -> None:
        while True:
            health_ok = self.data.is_healthy() and self.account.known
            if not health_ok:
                self.engine_state = "soft_paused"
                self.risk.trigger_safe_pause()
                self._write_status(self.engine_state)
                await asyncio.sleep(1)
                continue

            if self.engine_state in {"soft_paused", "recovering", "auto_resumed"}:
                if health_ok and not self.risk.reduce_only_mode:
                    self.engine_state = "running"
                elif health_ok:
                    self.engine_state = "auto_resumed"

            self.profile_mgr.maybe_update(self.data.market)
            self._sync_account_from_data_state()
            for symbol in self.cfg["symbols"]:
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
                candidates = []
                for strat_name, config_name in self.cfg["strategy_profiles"].get(symbol, {}).get(regime.value, []):
                    strat = self.strategies[strat_name]
                    signal = strat.generate(snap, regime, self.cfg["strategy_configs"][strat_name][config_name])
                    if signal:
                        candidates.append((strat_name, config_name, signal))
                cost_proxy = {
                    "spread": (snap.ask - snap.bid) / max(snap.price, 1e-9),
                    "slippage": self.profile_mgr.profiles.get(symbol).slippage_proxy if symbol in self.profile_mgr.profiles else 0.0,
                    "funding": self.profile_mgr.profiles.get(symbol).funding_behavior if symbol in self.profile_mgr.profiles else 0.0,
                }
                notional = abs(self.account.positions.get(symbol, PositionState(symbol=symbol)).qty) * snap.price
                exposure_penalty = notional / max(self.account.equity, 1e-9)
                profile = self.profile_mgr.profiles.get(symbol)
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
                    continue
                self.last_decision = decision.as_audit_payload()
                await self._execute_decision(decision)
            self._persist_state()
            self._write_status(self.engine_state)
            await asyncio.sleep(self.cfg["engine"]["decision_interval_sec"])

    async def _execute_decision(self, decision: DecisionRecord) -> None:
        side = decision.selected_side
        qty = max(0.0, self.cfg["sizing"]["base_qty"] * decision.sizing["confidence"])
        decision.side = side
        decision.qty = qty
        order = format_order(decision.symbol, side, qty)
        rr = self.risk.evaluate_order(order, self.account, self.data.market)
        decision.caps_status = {
            "safe_pause": self.risk.safe_pause,
            "reduce_only_mode": self.risk.reduce_only_mode,
            "risk_result": rr.reason,
        }
        if not rr.allowed:
            decision.blocked_reason = rr.reason
            self.audit.save_decision(decision)
            log_event("decision_blocked", decision.as_audit_payload())
            if rr.reason in {"kill_switch_triggered", "weekly_guard_triggered"}:
                self.engine_state = "hard_paused"
                await self.risk.panic_flatten(self.account, self.execution)
            return
        order.reduce_only = rr.reduce_only
        try:
            res = await self.execution.place_order(order)
        except BinanceRequestError as exc:
            if exc.category in {"auth", "rate_limit", "server", "timeout", "network"}:
                self.risk.trigger_safe_pause(reduce_only=True)
                self.engine_state = "soft_paused"
            decision.blocked_reason = f"execution_error:{exc.category}"
            self.audit.save_decision(decision)
            return
        self.audit.save_decision(decision)
        payload = decision.as_audit_payload()
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
                },
            )

    async def _submit_exit(self, symbol: str, reason: str) -> None:
        pos = self.account.positions.get(symbol)
        if not pos or abs(pos.qty) <= 0:
            self.position_mgr.clear(symbol)
            return
        side = "SELL" if pos.qty > 0 else "BUY"
        order = format_order(symbol, side, abs(pos.qty), reduce_only=True)
        rr = self.risk.evaluate_order(order, self.account, self.data.market)
        if not rr.allowed:
            return
        await self.execution.place_order(order)
        fill_price = self.data.get_snapshot(symbol).price if self.data.get_snapshot(symbol) else pos.entry_price
        if self.cfg.get("mode") == "paper":
            self.data.apply_paper_fill(symbol, side, abs(pos.qty), fill_price, reduce_only=True)
            self._sync_account_from_data_state()
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

    def _persist_state(self) -> None:
        payload = self.state_store.load()
        payload["engine_state"] = self.engine_state
        payload["position_manager_state"] = self.position_mgr.state
        payload["risk_state"] = self.risk.export_state()
        payload["symbol_profiles"] = {k: vars(v) for k, v in self.profile_mgr.profiles.items()}
        payload["candidate_registry_snapshot"] = self.candidate_registry.report()
        payload["review_queue"] = self.review_queue.list_ready()
        self.state_store.save(payload)
        self.data.persist_state(self.cfg.get("state", {}).get("data_state_file", "runtime/data_state.json"))

    def _write_status(self, state: str) -> None:
        write_status(
            self.cfg["telemetry"]["status_file"],
            {
                "state": state,
                "mode": self.cfg["mode"],
                "symbols": self.cfg["symbols"],
                "open_positions": {
                    sym: {"qty": pos.qty, "entry_price": pos.entry_price}
                    for sym, pos in self.account.positions.items()
                    if abs(pos.qty) > 0
                },
                "last_decision": self.last_decision,
                "ws_status": self.data.stream_health(),
                "account_sync_health": {
                    "known": self.account.known,
                    "last_event_age_sec": self.data.stream_health().get("account_last_event_age_sec"),
                },
                "current_regime": self.current_regimes,
                "safe_pause": self.risk.safe_pause,
                "reduce_only": self.risk.reduce_only_mode,
                "candidate_registry": self.candidate_registry.report(),
                "review_queue_size": len(self.review_queue.list_ready()),
                "llm_status": {"provider": self.cfg.get("llm", {}).get("provider"), "fallback": self.cfg.get("llm", {}).get("fallback_provider")},
                "last_review_result_location": "runtime/reviews",
                "risk_caps_status": {
                    "daily_pnl": self.account.daily_pnl,
                    "daily_loss_cap": self.cfg["risk"]["max_daily_loss"],
                    "weekly_loss_cap": self.cfg["risk"].get("max_weekly_loss"),
                    "total_exposure_notional": self.risk._exposure(self.account, self.data.market),
                    "total_exposure_cap": self.cfg["risk"]["max_total_exposure_notional"],
                    "leverage": self.account.leverage,
                    "max_leverage": self.cfg["risk"]["max_leverage"],
                },
                "ts": time.time(),
            },
        )
