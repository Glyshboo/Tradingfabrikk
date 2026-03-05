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
    selected_strategy: str
    selected_config: str
    selected_side: str
    sizing: Dict[str, float]
    blocked_reason: Optional[str] = None
