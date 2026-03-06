from __future__ import annotations

import asyncio
import time
from typing import Dict

from packages.core.models import AccountState, DecisionRecord, OrderRequest, PositionState
from packages.data.data_manager import DataManager
from packages.execution.adapters import BinanceRequestError, ExecutionAdapter, format_order
from packages.execution.position_manager import PositionManager
from packages.profiles.symbol_profile import SymbolProfileManager
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

    async def run(self) -> None:
        log_event("engine_start", {"mode": self.cfg["mode"]})
        tasks = [
            asyncio.create_task(self.data.run_market_stream()),
            asyncio.create_task(self.data.run_user_stream()),
            asyncio.create_task(self._decision_loop()),
        ]
        await asyncio.gather(*tasks)

    async def _decision_loop(self) -> None:
        while True:
            if not self.data.is_healthy():
                self.risk.trigger_safe_pause()
                log_event("safe_pause", {"reason": "data_or_user_stream_unhealthy"})
                log_event("alert", {"severity": "warning", "message": "Data/User stream unhealthy -> trading paused (fail-closed)"})
                self._write_status("SAFE_PAUSE")
                await asyncio.sleep(1)
                continue

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
            self._write_status("RUNNING")
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
            if rr.reason == "kill_switch_triggered":
                await self.risk.panic_flatten(self.account, self.execution)
            return
        order.reduce_only = rr.reduce_only
        try:
            res = await self.execution.place_order(order)
        except BinanceRequestError as exc:
            if exc.category in {"auth", "rate_limit", "server", "timeout", "network"}:
                self.risk.trigger_safe_pause(reduce_only=True)
            decision.blocked_reason = f"execution_error:{exc.category}"
            self.audit.save_decision(decision)
            log_event(
                "execution_error",
                {
                    "symbol": decision.symbol,
                    "error": str(exc),
                    "error_category": exc.category,
                    "safe_pause": self.risk.safe_pause,
                    "reduce_only": self.risk.reduce_only_mode,
                },
            )
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
codex/close-the-gap-to-production-ready-architecture-h2uz9x
                    {
                        "stop_price": decision.sizing.get("stop_price"),
                        "take_profit": decision.sizing.get("take_profit"),
                        "time_stop_bars": decision.sizing.get("time_stop_bars", 0),
                        "trail_mult": decision.sizing.get("trail_mult", 1.5),
                    },
                )
=======
                {
                    "stop_price": decision.sizing.get("stop_price"),
                    "take_profit": decision.sizing.get("take_profit"),
                    "time_stop_bars": decision.sizing.get("time_stop_bars", 0),
                },
            )
main

    async def _submit_exit(self, symbol: str, reason: str) -> None:
        pos = self.account.positions.get(symbol)
        if not pos or abs(pos.qty) <= 0:
            self.position_mgr.clear(symbol)
            return
        side = "SELL" if pos.qty > 0 else "BUY"
        order = format_order(symbol, side, abs(pos.qty), reduce_only=True)
        rr = self.risk.evaluate_order(order, self.account, self.data.market)
        if not rr.allowed:
            log_event("exit_blocked", {"symbol": symbol, "reason": rr.reason, "exit_reason": reason})
            return
        await self.execution.place_order(order)
        fill_price = self.data.get_snapshot(symbol).price if self.data.get_snapshot(symbol) else pos.entry_price
        if self.cfg.get("mode") == "paper":
            self.data.apply_paper_fill(symbol, side, abs(pos.qty), fill_price, reduce_only=True)
            self._sync_account_from_data_state()
        self.position_mgr.clear(symbol)
        log_event("position_exit", {"symbol": symbol, "reason": reason, "side": side, "qty": abs(pos.qty)})

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
            if last_event_ts is None:
                self.account.known = False
            else:
                self.account.known = (time.time() - float(last_event_ts)) <= (self.cfg["engine"]["stale_after_sec"] * 2)

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
                "risk_caps_status": {
                    "daily_pnl": self.account.daily_pnl,
                    "daily_loss_cap": self.cfg["risk"]["max_daily_loss"],
                    "total_exposure_notional": self.risk._exposure(self.account, self.data.market),
                    "total_exposure_cap": self.cfg["risk"]["max_total_exposure_notional"],
                    "leverage": self.account.leverage,
                    "max_leverage": self.cfg["risk"]["max_leverage"],
                },
                "ts": time.time(),
            },
        )
