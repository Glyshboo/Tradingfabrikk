from __future__ import annotations

import time

from packages.backtest.engine import CandleBacktester
from packages.data.data_manager import DataManager
from packages.research.candidate_registry import CandidateRegistry


class PaperSmokeWorker:
    def __init__(self, registry: CandidateRegistry, cfg: dict):
        self.registry = registry
        self.cfg = cfg
        self.bt = CandleBacktester()
        self._dm = DataManager(symbols=cfg.get("symbols", []), cache_dir="runtime/data_cache")

    def process(self) -> list[dict]:
        actions = []
        for row in self.registry.list_by_state(["paper_smoke_running"]):
            keep_in_paper = bool(row.get("meta", {}).get("keep_paper"))
            hold_until = float(row.get("meta", {}).get("hold_until_ts", 0.0) or 0.0)
            if keep_in_paper:
                self.registry.update_meta(row["id"], artifacts_patch={"paper_smoke_result": {"status": "kept_in_paper", "ts": time.time()}})
                continue
            if hold_until and hold_until > time.time():
                continue
            symbol = ((row.get("symbols") or ["MULTI"])[0]).upper()
            regime = ((row.get("regimes") or ["MIXED"])[0]).upper()
            strategy = row.get("strategy_family") or row.get("meta", {}).get("strategy_family") or "TrendCore"
            candles = self._dm.load_historical_candles(
                symbol=symbol,
                regime=regime,
                bars=int(self.cfg.get("paper_smoke", {}).get("bars", 48)),
                interval=self.cfg.get("paper_smoke", {}).get("interval", "1h"),
            )
            passed = False
            result = {"status": "insufficient_data", "ts": time.time(), "trades": 0, "pnl": 0.0, "sharpe_like": 0.0}
            if len(candles) >= 8:
                kind = row.get("candidate_kind") or row.get("meta", {}).get("candidate_kind", "config_tweak")
                profile = self.cfg.get("paper_smoke_profiles", {}).get(kind, {})
                bt_result = self.bt.run(
                    candles,
                    strategy_family=strategy,
                    strategy_config=(row.get("artifacts", {}).get("config_patch") or {}).get(strategy, {}),
                )
                min_trades = int(profile.get("min_trades", self.cfg.get("paper_smoke", {}).get("min_trades", 4)))
                min_pnl = float(profile.get("min_pnl", self.cfg.get("paper_smoke", {}).get("min_pnl", -1.0)))
                passed = bt_result.trades >= min_trades and bt_result.pnl >= min_pnl
                result = {
                    "status": "pass" if passed else "fail",
                    "ts": time.time(),
                    "trades": bt_result.trades,
                    "pnl": bt_result.pnl,
                    "sharpe_like": bt_result.sharpe_like,
                    "required_min_trades": min_trades,
                    "required_min_pnl": min_pnl,
                    "candidate_kind": kind,
                }
            self.registry.update_meta(
                row["id"],
                meta_patch={"lifecycle_reason": "paper_smoke_pass" if passed else "paper_smoke_fail"},
                artifacts_patch={"paper_smoke_result": result},
            )
            self.registry.transition(row["id"], "paper_smoke_pass" if passed else "paper_candidate_fail")
            actions.append({"id": row["id"], "result": result})
        return actions
