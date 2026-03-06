from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import List


@dataclass
class BacktestResult:
    trades: int
    pnl: float
    sharpe_like: float


class CandleBacktester:
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

    def _position_for_bar(self, strategy_family: str, candles: list[dict], i: int, config: dict | None = None) -> int:
        cfg = config or {}
        if i < 2:
            return 0
        close = candles[i]["close"]
        prev = candles[i - 1]["close"]
        prev2 = candles[i - 2]["close"]
        if strategy_family == "RangeMR":
            lookback = int(cfg.get("lookback", 8))
            if i < lookback:
                return 0
            window = [c["close"] for c in candles[i - lookback:i]]
            center = mean(window)
            span = max(max(window) - min(window), max(abs(center), 1e-9) * 0.002)
            z = (close - center) / span
            threshold = float(cfg.get("mean_revert_threshold", 0.28))
            if z > threshold:
                return -1
            if z < -threshold:
                return 1
            return 0
        momentum = (close - prev) + (prev - prev2)
        return 1 if momentum > 0 else -1 if momentum < 0 else 0

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
            position = self._position_for_bar(strategy_family, candles, i - 1, strategy_config)
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
