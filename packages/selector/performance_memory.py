from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class MemoryCell:
    sample_count: float = 0.0
    recent_pnl: float = 0.0
    hit_rate: float = 0.5
    avg_result: float = 0.0
    challenger_relative: float = 0.0
    last_ts: float = 0.0


class PerformanceMemory:
    def __init__(self, cfg: Dict[str, Any] | None = None):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.decay_half_life_sec = float(cfg.get("decay_half_life_sec", 12 * 3600))
        self.min_samples_for_full_weight = float(cfg.get("min_samples_for_full_weight", 25))
        self.max_adjustment = float(cfg.get("max_adjustment", 0.08))
        self.uncertainty_scale = float(cfg.get("uncertainty_scale", 0.02))
        self.max_uncertainty_penalty = float(cfg.get("max_uncertainty_penalty", 0.03))
        self.pnl_scale = float(cfg.get("pnl_scale", 1.0))
        self.weights = {
            "recent_pnl": float(cfg.get("weight_recent_pnl", 0.35)),
            "hit_rate": float(cfg.get("weight_hit_rate", 0.25)),
            "avg_result": float(cfg.get("weight_avg_result", 0.25)),
            "challenger_relative": float(cfg.get("weight_challenger_relative", 0.15)),
        }
        self.paper_window_sec = float(cfg.get("paper_window_sec", 300))
        self.state: Dict[str, Dict[str, float]] = {}

    def _key(self, symbol: str, regime: str, strategy: str, config: str) -> str:
        return f"{symbol}|{regime}|{strategy}|{config}"

    def _decay_factor(self, elapsed_sec: float) -> float:
        if elapsed_sec <= 0:
            return 1.0
        return 0.5 ** (elapsed_sec / max(self.decay_half_life_sec, 1.0))

    def _load_cell(self, key: str, now_ts: float) -> MemoryCell:
        raw = self.state.get(key)
        if not raw:
            return MemoryCell(last_ts=now_ts)
        cell = MemoryCell(
            sample_count=float(raw.get("sample_count", 0.0)),
            recent_pnl=float(raw.get("recent_pnl", 0.0)),
            hit_rate=float(raw.get("hit_rate", 0.5)),
            avg_result=float(raw.get("avg_result", 0.0)),
            challenger_relative=float(raw.get("challenger_relative", 0.0)),
            last_ts=float(raw.get("last_ts", 0.0)),
        )
        if cell.last_ts > 0 and now_ts > cell.last_ts:
            decay = self._decay_factor(now_ts - cell.last_ts)
            cell.sample_count *= decay
            cell.recent_pnl *= decay
            cell.avg_result *= decay
            cell.challenger_relative *= decay
            cell.hit_rate = 0.5 + ((cell.hit_rate - 0.5) * decay)
        cell.last_ts = now_ts
        return cell

    def _store_cell(self, key: str, cell: MemoryCell) -> None:
        self.state[key] = {
            "sample_count": round(max(0.0, cell.sample_count), 8),
            "recent_pnl": round(cell.recent_pnl, 8),
            "hit_rate": round(min(1.0, max(0.0, cell.hit_rate)), 8),
            "avg_result": round(cell.avg_result, 8),
            "challenger_relative": round(cell.challenger_relative, 8),
            "last_ts": float(cell.last_ts),
        }

    def update(
        self,
        symbol: str,
        regime: str,
        strategy: str,
        config: str,
        pnl: float,
        source: str,
        ts: float | None = None,
        challenger_relative: float = 0.0,
    ) -> None:
        if not self.enabled:
            return
        now_ts = float(ts or time.time())
        key = self._key(symbol, regime, strategy, config)
        cell = self._load_cell(key, now_ts)
        event_w = 0.8 if source == "challenger" else 1.0
        alpha = min(0.35, max(0.05, 1.0 / (cell.sample_count + 2.0)))
        pnl_norm = math.tanh(float(pnl) / max(self.pnl_scale, 1e-9))
        hit = 1.0 if pnl > 0 else 0.0

        cell.sample_count += event_w
        cell.recent_pnl = (1 - alpha) * cell.recent_pnl + (alpha * pnl_norm)
        cell.hit_rate = (1 - alpha) * cell.hit_rate + (alpha * hit)
        cell.avg_result = (1 - alpha) * cell.avg_result + (alpha * pnl_norm)
        if source == "challenger":
            rel = max(-1.0, min(1.0, challenger_relative))
            cell.challenger_relative = (1 - alpha) * cell.challenger_relative + (alpha * rel)
        self._store_cell(key, cell)

    def score_components(self, symbol: str, regime: str, strategy: str, config: str, ts: float | None = None) -> Dict[str, float]:
        now_ts = float(ts or time.time())
        key = self._key(symbol, regime, strategy, config)
        cell = self._load_cell(key, now_ts)
        if key in self.state:
            self._store_cell(key, cell)
        if not self.enabled or cell.sample_count <= 0:
            return {
                "learned_adjustment": 0.0,
                "uncertainty_penalty": 0.0,
                "memory_sample_count": 0.0,
                "memory_recent_pnl": 0.0,
                "memory_hit_rate": 0.5,
                "memory_avg_result": 0.0,
                "memory_challenger_relative": 0.0,
            }

        sample_weight = min(1.0, math.sqrt(cell.sample_count / max(self.min_samples_for_full_weight, 1.0)))
        raw = (
            self.weights["recent_pnl"] * cell.recent_pnl
            + self.weights["hit_rate"] * ((cell.hit_rate - 0.5) * 2.0)
            + self.weights["avg_result"] * cell.avg_result
            + self.weights["challenger_relative"] * cell.challenger_relative
        )
        learned = max(-self.max_adjustment, min(self.max_adjustment, raw * self.max_adjustment * sample_weight))
        uncertainty = min(
            self.max_uncertainty_penalty,
            self.uncertainty_scale * (1.0 - sample_weight) * (1.0 + abs(raw)),
        )
        return {
            "learned_adjustment": round(learned, 6),
            "uncertainty_penalty": round(uncertainty, 6),
            "memory_sample_count": round(cell.sample_count, 4),
            "memory_recent_pnl": round(cell.recent_pnl, 6),
            "memory_hit_rate": round(cell.hit_rate, 6),
            "memory_avg_result": round(cell.avg_result, 6),
            "memory_challenger_relative": round(cell.challenger_relative, 6),
        }

    def export_state(self) -> Dict[str, Dict[str, float]]:
        return dict(self.state)

    def import_state(self, payload: Dict[str, Dict[str, float]] | None) -> None:
        self.state = dict(payload or {})
