from __future__ import annotations

from dataclasses import dataclass
from typing import List

from packages.core.models import MarketSnapshot, Regime, StrategyContext
from packages.selector.regime_engine import RegimeEngine
from packages.strategies.range_mr import RangeMR
from packages.strategies.trend_core import TrendCore


@dataclass
class BacktestResult:
    trades: int
    pnl: float
    sharpe_like: float


class CandleBacktester:
    def __init__(self) -> None:
        self.regime_engine = RegimeEngine()
        self.strategies = {
            "TrendCore": TrendCore(),
            "RangeMR": RangeMR(),
        }

    def _as_candles(self, candles_or_prices: List[dict] | List[float]) -> list[dict]:
        if not candles_or_prices:
            return []
        first = candles_or_prices[0]
        if isinstance(first, dict):
            out = []
            for row in candles_or_prices:
                out.append(
                    {
                        "open": float(row.get("open", row.get("close", 0.0))),
                        "high": float(row.get("high", row.get("close", 0.0))),
                        "low": float(row.get("low", row.get("close", 0.0))),
                        "close": float(row.get("close", 0.0)),
                    }
                )
            return out
        prices = [float(x) for x in candles_or_prices]
        return [{"open": px, "high": px, "low": px, "close": px} for px in prices]

    def _compute_atr(self, candles: list[dict], i: int, period: int = 14) -> float | None:
        if i < period:
            return None
        true_ranges: list[float] = []
        for bar_idx in range(max(1, i - period + 1), i + 1):
            curr = candles[bar_idx]
            prev_close = float(candles[bar_idx - 1]["close"])
            high = float(curr["high"])
            low = float(curr["low"])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        if len(true_ranges) < period:
            return None
        return sum(true_ranges[-period:]) / period

    def _compute_rsi(self, candles: list[dict], i: int, period: int = 14) -> float | None:
        if i < period:
            return None
        closes = [float(c["close"]) for c in candles[i - period : i + 1]]
        gains: list[float] = []
        losses: list[float] = []
        for idx in range(1, len(closes)):
            diff = closes[idx] - closes[idx - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss <= 1e-12:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _snapshot_for_bar(self, candles: list[dict], i: int) -> MarketSnapshot:
        close = float(candles[i]["close"])
        # Backtest bruker candle-close syntetisk spread=0 for deterministisk signalparitet.
        return MarketSnapshot(
            symbol="BACKTEST",
            price=close,
            bid=close,
            ask=close,
            candle_close=float(candles[i - 1]["close"]) if i > 0 else close,
            atr=self._compute_atr(candles, i),
            rsi=self._compute_rsi(candles, i),
            ts=float(i),
        )

    def _signal_for_bar(self, strategy_family: str, candles: list[dict], i: int, strategy_config: dict | None = None) -> int:
        snapshot = self._snapshot_for_bar(candles, i)
        regime = self.regime_engine.classify(snapshot)
        return self.signal_for_snapshot(strategy_family, snapshot, regime, strategy_config)

    def signal_for_snapshot(
        self,
        strategy_family: str,
        snapshot: MarketSnapshot,
        regime: Regime,
        strategy_config: dict | None = None,
    ) -> int:
        strategy = self.strategies.get(strategy_family)
        if strategy is None:
            return 0
        signal = strategy.generate_for_context(
            StrategyContext(snapshot=snapshot, regime=regime, config=strategy_config or {})
        )
        if not signal:
            return 0
        return 1 if signal.side == "BUY" else -1 if signal.side == "SELL" else 0

    def run(
        self,
        candles_or_prices: List[dict] | List[float],
        fee_bps: float = 4.0,
        slippage_bps: float = 2.0,
        funding_bps_per_bar: float = 0.0,
        strategy_family: str = "TrendCore",
        strategy_config: dict | None = None,
    ) -> BacktestResult:
        candles = self._as_candles(candles_or_prices)
        if len(candles) < 4:
            return BacktestResult(0, 0.0, 0.0)
        pnl = 0.0
        trades = 0
        prev_pos = 0
        costs_bps = (fee_bps + slippage_bps + funding_bps_per_bar) / 10000
        for i in range(2, len(candles)):
            position = self._signal_for_bar(strategy_family, candles, i - 1, strategy_config)
            close_now = candles[i]["close"]
            close_prev = candles[i - 1]["close"]
            ret = 0.0 if close_prev <= 0 else (close_now - close_prev) / close_prev
            if position != 0:
                pnl += position * ret * close_now
                pnl -= close_now * costs_bps
                trades += 1
            if prev_pos != 0 and position != prev_pos:
                pnl -= close_now * costs_bps
            prev_pos = position
        sharpe_like = pnl / max(1.0, trades**0.5)
        return BacktestResult(trades=trades, pnl=round(pnl, 6), sharpe_like=round(sharpe_like, 6))

    def run_walk_forward(
        self,
        candles_or_prices: List[dict] | List[float],
        train_ratio: float = 0.7,
        fee_bps: float = 4.0,
        slippage_bps: float = 2.0,
        funding_bps_per_bar: float = 0.0,
        strategy_family: str = "TrendCore",
        strategy_config: dict | None = None,
    ) -> tuple[BacktestResult, BacktestResult]:
        candles = self._as_candles(candles_or_prices)
        split = max(4, min(len(candles) - 4, int(len(candles) * train_ratio)))
        in_sample = self.run(
            candles[:split],
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            funding_bps_per_bar=funding_bps_per_bar,
            strategy_family=strategy_family,
            strategy_config=strategy_config,
        )
        out_sample = self.run(
            candles[split:],
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            funding_bps_per_bar=funding_bps_per_bar,
            strategy_family=strategy_family,
            strategy_config=strategy_config,
        )
        return in_sample, out_sample
