from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class AutoResearchDecision:
    should_run: bool
    reasons: list[str]
    cooldown_blocked: bool
    details: dict[str, Any]


class AutoResearchOrchestrator:
    def __init__(
        self,
        cfg: dict,
        *,
        status_file: str,
        engine_state_file: str,
        state_file: str,
        deterministic_runner: Callable[[list[str], dict[str, Any]], dict[str, Any]],
        llm_runner: Callable[[list[str], dict[str, Any]], dict[str, Any]] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.cfg = cfg or {}
        self.status_file = pathlib.Path(status_file)
        self.engine_state_file = pathlib.Path(engine_state_file)
        self.state_file = pathlib.Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.deterministic_runner = deterministic_runner
        self.llm_runner = llm_runner
        self.now_fn = now_fn or time.time

    def _load_json(self, path: pathlib.Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _load_state(self) -> dict[str, Any]:
        payload = self._load_json(self.state_file)
        return {
            "last_run_ts": float(payload.get("last_run_ts", 0.0) or 0.0),
            "last_regimes": payload.get("last_regimes", {}),
            "history": payload.get("history", [])[-200:],
        }

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def evaluate(self) -> AutoResearchDecision:
        now = self.now_fn()
        status = self._load_json(self.status_file)
        engine_state = self._load_json(self.engine_state_file)
        state = self._load_state()
        reasons: list[str] = []
        details: dict[str, Any] = {}
        trigger_cfg = self.cfg.get("triggers", {})

        schedule_hours = float(trigger_cfg.get("research_schedule_hours", 0) or 0)
        if schedule_hours > 0:
            elapsed_hours = (now - state["last_run_ts"]) / 3600 if state["last_run_ts"] else 10**9
            details["schedule_elapsed_hours"] = elapsed_hours
            if elapsed_hours >= schedule_hours:
                reasons.append("schedule")

        window_hours = float(trigger_cfg.get("performance_drop_window_hours", 0) or 0)
        if window_hours > 0:
            drop_threshold = float(
                trigger_cfg.get("performance_drop_threshold", (self.cfg.get("risk", {}).get("max_daily_loss", 0) or 0) * -0.5)
            )
            perf_rows = engine_state.get("strategy_performance_history", [])
            cutoff_ts = now - (window_hours * 3600)
            recent = [r for r in perf_rows if float(r.get("ts", 0) or 0) >= cutoff_ts]
            blocked_ratio = 0.0
            if recent:
                blocked_ratio = sum(1 for r in recent if r.get("blocked")) / len(recent)
            daily_pnl = float((status.get("risk_caps_status") or {}).get("daily_pnl", 0.0) or 0.0)
            details["performance_window_rows"] = len(recent)
            details["blocked_ratio"] = blocked_ratio
            details["daily_pnl"] = daily_pnl
            if daily_pnl <= drop_threshold and (len(recent) >= int(trigger_cfg.get("min_performance_observations", 10) or 10) or blocked_ratio >= 0.6):
                reasons.append("performance_drop")

        min_paper_trades = int(trigger_cfg.get("min_paper_trades_before_research", 0) or 0)
        if min_paper_trades > 0:
            paper_rows = engine_state.get("paper_trade_history", [])
            details["paper_trade_count"] = len(paper_rows)
            if len(paper_rows) < min_paper_trades:
                return AutoResearchDecision(False, [], False, {**details, "guard": "min_paper_trades_not_met"})

        if bool(trigger_cfg.get("regime_shift_trigger", False)):
            current_regimes = status.get("current_regime") if isinstance(status.get("current_regime"), dict) else {}
            prev_regimes = state.get("last_regimes") if isinstance(state.get("last_regimes"), dict) else {}
            if current_regimes and prev_regimes and current_regimes != prev_regimes:
                reasons.append("regime_shift")
            details["current_regimes"] = current_regimes

        streak_limit = int(trigger_cfg.get("challenger_failure_streak", 0) or 0)
        if streak_limit > 0:
            eval_rows = ((status.get("paper_candidate") or {}).get("challenger_evaluations") or [])
            streak = 0
            for row in reversed(eval_rows):
                if row.get("status") != "evaluated":
                    continue
                pnl = row.get("result_pnl")
                if pnl is None:
                    continue
                if float(pnl) <= 0:
                    streak += 1
                else:
                    break
            details["challenger_failure_streak"] = streak
            if streak >= streak_limit:
                reasons.append("challenger_failure_streak")

        cooldown_hours = float(trigger_cfg.get("cooldown_hours", 0) or 0)
        cooldown_blocked = False
        if reasons and cooldown_hours > 0 and state["last_run_ts"] > 0:
            if now - state["last_run_ts"] < (cooldown_hours * 3600):
                cooldown_blocked = True
                details["cooldown_remaining_sec"] = (cooldown_hours * 3600) - (now - state["last_run_ts"])

        return AutoResearchDecision(bool(reasons) and not cooldown_blocked, reasons, cooldown_blocked, details)

    def run_once(self) -> dict[str, Any]:
        now = self.now_fn()
        decision = self.evaluate()
        status = self._load_json(self.status_file)
        engine_state = self._load_json(self.engine_state_file)
        state = self._load_state()
        context = {
            "status": status,
            "engine_state": {
                "paper_trade_history": engine_state.get("paper_trade_history", [])[-200:],
                "strategy_performance_history": engine_state.get("strategy_performance_history", [])[-200:],
                "challenger_eval_history": engine_state.get("challenger_eval_history", [])[-200:],
            },
            "decision_details": decision.details,
            "mode": self.cfg.get("mode", "paper"),
        }

        report = {
            "triggered": False,
            "reasons": decision.reasons,
            "cooldown_blocked": decision.cooldown_blocked,
            "details": decision.details,
            "deterministic": {"ran": False},
            "llm": {"ran": False},
            "ts": now,
        }
        if not decision.should_run:
            return report

        deterministic_result = self.deterministic_runner(decision.reasons, context)
        report["deterministic"] = {"ran": True, **(deterministic_result or {})}
        report["triggered"] = True

        llm_enabled = bool((self.cfg.get("llm") or {}).get("enabled", False)) and bool((self.cfg.get("llm") or {}).get("run_after_deterministic", False))
        if llm_enabled and self.llm_runner and not (deterministic_result or {}).get("failed", False):
            llm_result = self.llm_runner(decision.reasons, context)
            report["llm"] = {"ran": True, **(llm_result or {})}

        history = state.get("history", [])
        history.append({"ts": now, "reasons": decision.reasons, "report": report})
        state["last_run_ts"] = now
        current_regime = status.get("current_regime")
        if isinstance(current_regime, dict):
            state["last_regimes"] = current_regime
        state["history"] = history[-200:]
        self._save_state(state)
        return report
