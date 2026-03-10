from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from packages.core.models import MarketSnapshot, Regime, StrategyComposition, StrategyContext, StrategySignal


class StrategyPlugin(ABC):
    name: str
    eligible_regimes: set[Regime]

    @abstractmethod
    def generate_for_context(self, context: StrategyContext) -> StrategySignal | None:
        raise NotImplementedError

    @abstractmethod
    def generate(self, snapshot: MarketSnapshot, regime: Regime, config: dict) -> StrategySignal | None:
        return self.generate_for_context(StrategyContext(snapshot=snapshot, regime=regime, config=config))


class EntryFamily(ABC):
    name: str

    @abstractmethod
    def generate_entry(self, context: StrategyContext) -> StrategySignal | None:
        raise NotImplementedError


class FilterModule(ABC):
    name: str

    @abstractmethod
    def allow(self, context: StrategyContext, signal: StrategySignal) -> bool:
        raise NotImplementedError


class ExitPack(ABC):
    name: str

    @abstractmethod
    def apply(self, context: StrategyContext, signal: StrategySignal) -> StrategySignal | None:
        raise NotImplementedError


@dataclass
class StrategyEvaluator:
    strategies: dict[str, StrategyPlugin]
    entry_families: dict[str, EntryFamily]
    filter_modules: dict[str, FilterModule]
    filter_packs: dict[str, list[str]]
    exit_packs: dict[str, ExitPack]
    default_compositions: dict[str, StrategyComposition]

    def evaluate(self, strategy_name: str, context: StrategyContext) -> StrategySignal | None:
        signal, _ = self.evaluate_with_diagnostics(strategy_name, context)
        return signal

    def evaluate_with_diagnostics(self, strategy_name: str, context: StrategyContext) -> tuple[StrategySignal | None, dict]:
        composition = self._resolve_composition(strategy_name, context.config)
        if composition is None:
            strategy = self.strategies.get(strategy_name)
            if strategy is None:
                return None, {"reason": "strategy_not_found"}
            signal = strategy.generate_for_context(context)
            return signal, {"reason": "entry_no_signal" if signal is None else "ok", "entry_family": strategy_name}

        entry = self.entry_families.get(composition.entry_family)
        exit_pack = self.exit_packs.get(composition.exit_pack)
        if entry is None or exit_pack is None:
            return None, {"reason": "invalid_composition"}

        signal = entry.generate_entry(context)
        if signal is None:
            return None, {"reason": "entry_no_signal", "entry_family": composition.entry_family, "filter_pack": composition.filter_pack, "exit_pack": composition.exit_pack}

        module_names = list(self.filter_packs.get(composition.filter_pack, [])) + list(composition.filter_modules)
        for module_name in module_names:
            module = self.filter_modules.get(module_name)
            if module is None:
                return None, {"reason": "missing_filter_module", "filter_module": module_name, "entry_family": composition.entry_family}
            if not module.allow(context, signal):
                return None, {
                    "reason": f"blocked_by_filter:{module_name}",
                    "filter_module": module_name,
                    "entry_family": composition.entry_family,
                    "filter_pack": composition.filter_pack,
                    "exit_pack": composition.exit_pack,
                }

        out = exit_pack.apply(context, signal)
        if out is None:
            return None, {"reason": f"blocked_by_exit:{composition.exit_pack}", "entry_family": composition.entry_family, "exit_pack": composition.exit_pack}
        return out, {
            "reason": "ok",
            "entry_family": composition.entry_family,
            "filter_pack": composition.filter_pack,
            "filter_modules": module_names,
            "exit_pack": composition.exit_pack,
            "setup_quality": float(getattr(out, "confidence", 0.0) or 0.0),
        }

    def _resolve_composition(self, strategy_name: str, config: dict) -> StrategyComposition | None:
        composition_cfg = config.get("composition") if isinstance(config, dict) else None
        if isinstance(composition_cfg, dict):
            entry_family = composition_cfg.get("entry_family")
            if not isinstance(entry_family, str) or not entry_family:
                return None
            filter_pack = composition_cfg.get("filter_pack", "none")
            exit_pack = composition_cfg.get("exit_pack", "passthrough")
            modules = composition_cfg.get("filter_modules", [])
            return StrategyComposition(
                entry_family=entry_family,
                filter_pack=filter_pack if isinstance(filter_pack, str) else "none",
                exit_pack=exit_pack if isinstance(exit_pack, str) else "passthrough",
                filter_modules=[m for m in modules if isinstance(m, str)],
            )
        return self.default_compositions.get(strategy_name)
