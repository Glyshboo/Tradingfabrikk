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
        composition = self._resolve_composition(strategy_name, context.config)
        if composition is None:
            strategy = self.strategies.get(strategy_name)
            if strategy is None:
                return None
            return strategy.generate_for_context(context)

        entry = self.entry_families.get(composition.entry_family)
        exit_pack = self.exit_packs.get(composition.exit_pack)
        if entry is None or exit_pack is None:
            return None

        signal = entry.generate_entry(context)
        if signal is None:
            return None

        module_names = list(self.filter_packs.get(composition.filter_pack, [])) + list(composition.filter_modules)
        for module_name in module_names:
            module = self.filter_modules.get(module_name)
            if module is None:
                return None
            if not module.allow(context, signal):
                return None

        return exit_pack.apply(context, signal)

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
