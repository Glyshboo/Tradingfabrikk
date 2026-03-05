from __future__ import annotations

import asyncio
import time
from typing import Dict

from packages.core.models import AccountState, DecisionRecord, OrderRequest, PositionState
from packages.data.data_manager import DataManager
from packages.execution.adapters import BinanceRequestError, ExecutionAdapter, format_order
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
            for symbol in self.cfg["symbols"]:
                snap = self.data.get_snapshot(symbol)
                if not snap:
                    continue
                regime = self.regime.classify(snap)
                candidates = []
                for strat_name, config_name in self.cfg["strategy_profiles"].get(symbol, {}).get(regime.value, []):
                    strat = self.strategies[strat_name]
                    signal = strat.generate(snap, regime, self.cfg["strategy_configs"][strat_name][config_name])
                    if signal:
                        candidates.append((strat_name, config_name, signal))
                cost_proxy = {
                    "spread": (snap.ask - snap.bid) / max(snap.price, 1e-9),
                    "slippage": self.profile_mgr.profiles.get(symbol).slippage_proxy if symbol in self.profile_mgr.profiles else 0.0,
                    "funding": 0.0,
                }
                decision = self.selector.select(symbol, regime, candidates, cost_proxy, exposure_penalty=0.0)
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
