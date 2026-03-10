from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass
class OverlayResolution:
    symbol: str
    regime: str
    runtime_model: str
    candidate_id: str | None
    strategy_profiles: dict
    strategy_configs: dict
    blocker: str | None = None


@dataclass
class RuntimeSelection:
    champion: OverlayResolution
    challengers: list[OverlayResolution]


_ALLOWED_TOP_LEVEL_PATCH_KEYS = {"strategy_configs", "strategy_profiles", "selector", "sizing"}
_ALLOWED_SELECTOR_KEYS = {"base_edge"}
_ALLOWED_SIZING_KEYS = {"base_qty"}


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in (patch or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def validate_runtime_patch(baseline_cfg: dict, config_patch: dict | None, strategy_profile_patch: dict | None = None) -> tuple[bool, list[str]]:
    errors: list[str] = []
    cfg_patch = config_patch or {}
    if not isinstance(cfg_patch, dict):
        return False, ["config_patch_not_dict"]
    unsupported = sorted(set(cfg_patch.keys()) - _ALLOWED_TOP_LEVEL_PATCH_KEYS)
    if unsupported:
        errors.append(f"unsupported_patch_keys:{','.join(unsupported)}")
    selector_patch = cfg_patch.get("selector", {})
    if selector_patch and not isinstance(selector_patch, dict):
        errors.append("selector_patch_not_dict")
    elif isinstance(selector_patch, dict):
        selector_unsupported = sorted(set(selector_patch.keys()) - _ALLOWED_SELECTOR_KEYS)
        if selector_unsupported:
            errors.append(f"unsupported_selector_keys:{','.join(selector_unsupported)}")
    sizing_patch = cfg_patch.get("sizing", {})
    if sizing_patch and not isinstance(sizing_patch, dict):
        errors.append("sizing_patch_not_dict")
    elif isinstance(sizing_patch, dict):
        sizing_unsupported = sorted(set(sizing_patch.keys()) - _ALLOWED_SIZING_KEYS)
        if sizing_unsupported:
            errors.append(f"unsupported_sizing_keys:{','.join(sizing_unsupported)}")

    symbols = set(baseline_cfg.get("symbols", []))
    profiles = cfg_patch.get("strategy_profiles", {})
    if profiles and not isinstance(profiles, dict):
        errors.append("strategy_profiles_patch_not_dict")
    elif isinstance(profiles, dict):
        bad_symbols = sorted(set(profiles.keys()) - symbols)
        if bad_symbols:
            errors.append(f"unknown_symbols_in_strategy_profiles:{','.join(bad_symbols)}")

    configs = cfg_patch.get("strategy_configs", {})
    if configs and not isinstance(configs, dict):
        errors.append("strategy_configs_patch_not_dict")
    elif isinstance(configs, dict):
        known_strats = set((baseline_cfg.get("strategy_configs") or {}).keys())
        bad_strats = sorted(set(configs.keys()) - known_strats)
        if bad_strats:
            errors.append(f"unknown_strategies_in_strategy_configs:{','.join(bad_strats)}")

    spp = strategy_profile_patch or {}
    if spp and not isinstance(spp, dict):
        errors.append("strategy_profile_patch_not_dict")
    elif isinstance(spp, dict):
        bad_symbols = sorted(set(spp.keys()) - symbols)
        if bad_symbols:
            errors.append(f"unknown_symbols_in_strategy_profile_patch:{','.join(bad_symbols)}")

    return len(errors) == 0, errors


class CandidateRuntimeOverlayManager:
    def __init__(self, baseline_cfg: dict, micro_live_cfg: dict | None = None, paper_cfg: dict | None = None):
        self.baseline_cfg = copy.deepcopy(baseline_cfg)
        self.micro_live_cfg = micro_live_cfg or {}
        self.paper_cfg = paper_cfg or {}
        self.active: dict[str, dict] = {}
        self.symbol_to_candidates: dict[str, list[str]] = {s: [] for s in baseline_cfg.get("symbols", [])}

    def rebuild(self, rows: list[dict], mode: str) -> None:
        self.active = {}
        self.symbol_to_candidates = {s: [] for s in self.baseline_cfg.get("symbols", [])}
        for row in rows:
            cid = row.get("id")
            if not cid:
                continue
            lane = self._lane_for_state(row.get("state"), mode)
            if lane is None:
                continue
            artifacts = row.get("artifacts", {})
            config_patch = artifacts.get("config_patch") or row.get("meta", {}).get("config_patch") or {}
            profile_patch = artifacts.get("strategy_profile_patch") or row.get("meta", {}).get("strategy_profile_patch") or {}
            ok, errors = validate_runtime_patch(self.baseline_cfg, config_patch, profile_patch)
            if not ok:
                self.active[cid] = {"id": cid, "lane": lane, "state": row.get("state"), "blocked": True, "reason": ";".join(errors), "symbols": []}
                continue
            overlay_cfg = _deep_merge(self.baseline_cfg, config_patch)
            if profile_patch:
                merged_profiles = _deep_merge(overlay_cfg.get("strategy_profiles", {}), profile_patch)
                overlay_cfg["strategy_profiles"] = merged_profiles
            raw_symbols = row.get("symbols") or row.get("meta", {}).get("symbols") or []
            symbols = [s for s in raw_symbols if s in self.symbol_to_candidates] or list(self.symbol_to_candidates.keys())
            self.active[cid] = {
                "id": cid,
                "lane": lane,
                "state": row.get("state"),
                "blocked": False,
                "reason": "",
                "symbols": symbols,
                "overlay_config": overlay_cfg,
                "updated_ts": row.get("updated_ts", 0.0),
            }
            for sym in symbols:
                self.symbol_to_candidates[sym].append(cid)

        for sym, cids in self.symbol_to_candidates.items():
            cids.sort(key=lambda c: float(self.active.get(c, {}).get("updated_ts") or 0.0), reverse=True)
            self.symbol_to_candidates[sym] = cids

    def resolve(self, symbol: str, regime: str) -> OverlayResolution:
        baseline = OverlayResolution(
            symbol=symbol,
            regime=regime,
            runtime_model="baseline",
            candidate_id=None,
            strategy_profiles=self.baseline_cfg.get("strategy_profiles", {}),
            strategy_configs=self.baseline_cfg.get("strategy_configs", {}),
        )
        cands = self.symbol_to_candidates.get(symbol, [])
        if not cands:
            return baseline
        eligible = [self.active[cid] for cid in cands if not self.active[cid].get("blocked")]
        if len(eligible) > 1:
            return OverlayResolution(
                symbol=symbol,
                regime=regime,
                runtime_model="baseline",
                candidate_id=None,
                strategy_profiles=self.baseline_cfg.get("strategy_profiles", {}),
                strategy_configs=self.baseline_cfg.get("strategy_configs", {}),
                blocker="multiple_candidate_overlays_for_symbol",
            )
        if not eligible:
            first = self.active.get(cands[0], {})
            return OverlayResolution(
                symbol=symbol,
                regime=regime,
                runtime_model="baseline",
                candidate_id=None,
                strategy_profiles=self.baseline_cfg.get("strategy_profiles", {}),
                strategy_configs=self.baseline_cfg.get("strategy_configs", {}),
                blocker=first.get("reason") or "blocked_candidate_overlay",
            )
        row = eligible[0]
        cfg = row["overlay_config"]
        return OverlayResolution(
            symbol=symbol,
            regime=regime,
            runtime_model=f"challenger:{row['lane']}",
            candidate_id=row["id"],
            strategy_profiles=cfg.get("strategy_profiles", {}),
            strategy_configs=cfg.get("strategy_configs", {}),
        )

    def resolve_runtime(self, symbol: str, regime: str, mode: str) -> RuntimeSelection:
        baseline = OverlayResolution(
            symbol=symbol,
            regime=regime,
            runtime_model="baseline",
            candidate_id=None,
            strategy_profiles=self.baseline_cfg.get("strategy_profiles", {}),
            strategy_configs=self.baseline_cfg.get("strategy_configs", {}),
        )
        cids = self.symbol_to_candidates.get(symbol, [])
        eligible = [self.active[cid] for cid in cids if not self.active[cid].get("blocked")]
        if mode == "paper":
            challengers: list[OverlayResolution] = []
            for row in eligible:
                if row.get("lane") != "paper_candidate":
                    continue
                cfg = row["overlay_config"]
                challengers.append(
                    OverlayResolution(
                        symbol=symbol,
                        regime=regime,
                        runtime_model=f"challenger:{row['lane']}",
                        candidate_id=row["id"],
                        strategy_profiles=cfg.get("strategy_profiles", {}),
                        strategy_configs=cfg.get("strategy_configs", {}),
                    )
                )
            return RuntimeSelection(champion=baseline, challengers=challengers)

        return RuntimeSelection(champion=self.resolve(symbol, regime), challengers=[])

    def status(self) -> dict:
        return {
            "active": {
                cid: {
                    "lane": row.get("lane"),
                    "state": row.get("state"),
                    "blocked": row.get("blocked"),
                    "reason": row.get("reason"),
                    "symbols": row.get("symbols", []),
                }
                for cid, row in self.active.items()
            },
            "by_symbol": self.symbol_to_candidates,
        }

    def _lane_for_state(self, state: str | None, mode: str) -> str | None:
        if state in {"approved_for_micro_live", "micro_live_active", "micro_live_resumed", "micro_live_recovering"}:
            return "micro_live"
        if state in {"approved_for_live_full", "live_full_active"} and mode == "live":
            return "live_full"
        if state in {"paper_candidate_active", "paper_candidate_paused", "paper_candidate_winning", "paper_candidate_fading", "challenger_active", "challenger_evaluated"} and mode == "paper":
            return "paper_candidate"
        return None
