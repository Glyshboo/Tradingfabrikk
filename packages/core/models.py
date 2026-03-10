from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Regime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOL = "HIGH_VOL"
    ILLIQUID = "ILLIQUID"


@dataclass
class MarketSnapshot:
    symbol: str
    price: float
    bid: float
    ask: float
    candle_close: Optional[float] = None
    atr: Optional[float] = None
    rsi: Optional[float] = None
    trend_slope: Optional[float] = None
    realized_volatility: Optional[float] = None
    spread_bps: Optional[float] = None
    atr_pct_of_price: Optional[float] = None
    session_bucket: Optional[str] = None
    hour_bucket: Optional[int] = None
    range_compression_score: Optional[float] = None
    breakout_distance_from_recent_range: Optional[float] = None
    rsi_1h: Optional[float] = None
    rsi_4h: Optional[float] = None
    atr_1h: Optional[float] = None
    atr_4h: Optional[float] = None
    ts: float = 0.0


@dataclass
class PositionState:
    symbol: str
    qty: float = 0.0
    entry_price: float = 0.0


@dataclass
class AccountState:
    equity: float
    daily_pnl: float
    positions: Dict[str, PositionState] = field(default_factory=dict)
    leverage: float = 1.0
    known: bool = True


@dataclass
class StrategySignal:
    symbol: str
    side: str
    confidence: float
    stop_price: Optional[float]
    take_profit: Optional[float]
    reason: str
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyContext:
    snapshot: MarketSnapshot
    regime: Regime
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderRequest:
    symbol: str
    side: str
    qty: float
    type: str = "MARKET"
    reduce_only: bool = False


@dataclass
class DecisionRecord:
    symbol: str
    regime: str
    eligible_strategies: list[str]
    score_breakdown: Dict[str, float]
    score_components: Dict[str, Dict[str, float]] = field(default_factory=dict)
    selected_candidate: str = ""
    selected_strategy: str = ""
    selected_config: str = ""
    selected_side: str = ""
    sizing: Dict[str, float] = field(default_factory=dict)
    side: str = ""
    qty: float = 0.0
    caps_status: Dict[str, Any] = field(default_factory=dict)
    blocked_reason: Optional[str] = None
    runtime_model: str = "baseline"
    overlay_candidate_id: str = ""

    def as_audit_payload(self) -> Dict[str, Any]:
        selected_candidate = self.selected_candidate or f"{self.selected_strategy}:{self.selected_config}"
        side = self.side or self.selected_side
        return {
            "symbol": self.symbol,
            "regime": self.regime,
            "eligible_strategies": list(self.eligible_strategies),
            "score_breakdown": dict(self.score_breakdown),
            "score_components": {k: dict(v) for k, v in self.score_components.items()},
            "selected_candidate": selected_candidate,
            "selected_strategy": self.selected_strategy,
            "selected_config": self.selected_config,
            "selected_side": self.selected_side,
            "side": side,
            "qty": self.qty,
            "sizing": dict(self.sizing),
            "caps_status": dict(self.caps_status),
            "blocked_reason": self.blocked_reason,
            "runtime_model": self.runtime_model,
            "overlay_candidate_id": self.overlay_candidate_id,
        }
