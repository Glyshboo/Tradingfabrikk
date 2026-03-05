from __future__ import annotations

import pathlib
from typing import Any, Dict

import yaml


REQUIRED_TOP_LEVEL_KEYS = {
    "mode",
    "symbols",
    "account",
    "engine",
    "sizing",
    "risk",
    "selector",
    "strategy_configs",
    "strategy_profiles",
    "telemetry",
}


def _validate_config(cfg: Dict[str, Any], path: str) -> None:
    missing_keys = sorted(REQUIRED_TOP_LEVEL_KEYS - set(cfg.keys()))
    if missing_keys:
        raise ValueError(f"Invalid config {path}: missing keys: {', '.join(missing_keys)}")

    mode = cfg.get("mode")
    if mode not in {"paper", "live"}:
        raise ValueError(f"Invalid config {path}: mode must be 'paper' or 'live', got: {mode!r}")

    symbols = cfg.get("symbols")
    if not isinstance(symbols, list) or not symbols or not all(isinstance(s, str) and s for s in symbols):
        raise ValueError(f"Invalid config {path}: symbols must be a non-empty list of strings")

    strategy_profiles = cfg.get("strategy_profiles", {})
    missing_symbol_profiles = [s for s in symbols if s not in strategy_profiles]
    if missing_symbol_profiles:
        raise ValueError(
            f"Invalid config {path}: strategy_profiles missing symbols: {', '.join(missing_symbol_profiles)}"
        )


def load_config(path: str) -> Dict[str, Any]:
    with pathlib.Path(path).open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid config {path}: expected top-level mapping")
    _validate_config(cfg, path)
    return cfg
