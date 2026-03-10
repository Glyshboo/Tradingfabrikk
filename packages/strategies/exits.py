from __future__ import annotations

from dataclasses import replace

from packages.core.models import StrategyContext, StrategySignal
from packages.strategies.base import ExitPack


class PassthroughExitPack(ExitPack):
    name = "passthrough"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        return signal


class ProtectiveExitPack(ExitPack):
    name = "protective"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        if signal.stop_price is None:
            return None
        meta = dict(signal.meta)
        meta.setdefault("exit_pack", self.name)
        return replace(signal, meta=meta)


class FixedRRExitPack(ExitPack):
    name = "fixed_rr"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        if signal.stop_price is None:
            return None
        cfg = (context.config.get("exits", {}) or {}).get(self.name, {}) if isinstance(context.config, dict) else {}
        rr = float(cfg.get("rr", 1.8))
        entry = context.snapshot.price
        risk = abs(entry - signal.stop_price)
        if risk <= 0:
            return None
        take_profit = entry + risk * rr if signal.side == "BUY" else entry - risk * rr
        meta = dict(signal.meta)
        meta.update({"exit_pack": self.name, "rr": rr})
        return replace(signal, take_profit=take_profit, meta=meta)


class ATRTrailExitPack(ExitPack):
    name = "atr_trail"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        if signal.stop_price is None:
            return None
        cfg = (context.config.get("exits", {}) or {}).get(self.name, {}) if isinstance(context.config, dict) else {}
        trail_mult = float(cfg.get("trail_mult", 1.5))
        meta = dict(signal.meta)
        meta.update({"exit_pack": self.name, "trail_mult": trail_mult})
        return replace(signal, meta=meta)


class PartialTPRunnerExitPack(ExitPack):
    name = "partial_tp_runner"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        if signal.stop_price is None:
            return None
        cfg = (context.config.get("exits", {}) or {}).get(self.name, {}) if isinstance(context.config, dict) else {}
        entry = context.snapshot.price
        risk = abs(entry - signal.stop_price)
        if risk <= 0:
            return None
        partial_rr = float(cfg.get("partial_rr", 1.0))
        partial_take = entry + risk * partial_rr if signal.side == "BUY" else entry - risk * partial_rr
        partial_fraction = float(cfg.get("partial_fraction", 0.5))
        runner_trail_mult = float(cfg.get("runner_trail_mult", 1.2))
        meta = dict(signal.meta)
        meta.update(
            {
                "exit_pack": self.name,
                "partial_take_profit": partial_take,
                "partial_fraction": max(0.0, min(1.0, partial_fraction)),
                "trail_mult": runner_trail_mult,
            }
        )
        return replace(signal, meta=meta)


class TimeDecayExitPack(ExitPack):
    name = "time_decay_exit"

    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        cfg = (context.config.get("exits", {}) or {}).get(self.name, {}) if isinstance(context.config, dict) else {}
        bars = int(cfg.get("max_bars", 12))
        if bars <= 0:
            return None
        meta = dict(signal.meta)
        meta.update({"exit_pack": self.name, "time_stop_bars": bars})
        return replace(signal, meta=meta)
