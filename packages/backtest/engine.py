from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class BacktestResult:
    trades: int
    pnl: float
    sharpe_like: float


class CandleBacktester:
    def run(
        self,
        prices: List[float],
        fee_bps: float = 4.0,
        slippage_bps: float = 2.0,
        funding_bps_per_bar: float = 0.0,
    ) -> BacktestResult:
        if len(prices) < 3:
            return BacktestResult(0, 0.0, 0.0)
        pnl = 0.0
        trades = 0
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            gross = diff
            cost = prices[i] * ((fee_bps + slippage_bps + funding_bps_per_bar) / 10000)
            pnl += gross - cost
            trades += 1
        sharpe_like = pnl / max(1.0, trades**0.5)
        return BacktestResult(trades=trades, pnl=round(pnl, 6), sharpe_like=round(sharpe_like, 6))

    def run_walk_forward(
        self,
        prices: List[float],
        train_ratio: float = 0.7,
        fee_bps: float = 4.0,
        slippage_bps: float = 2.0,
        funding_bps_per_bar: float = 0.0,
    ) -> tuple[BacktestResult, BacktestResult]:
        split = max(3, min(len(prices) - 3, int(len(prices) * train_ratio)))
        in_sample = self.run(prices[:split], fee_bps=fee_bps, slippage_bps=slippage_bps, funding_bps_per_bar=funding_bps_per_bar)
        out_sample = self.run(prices[split:], fee_bps=fee_bps, slippage_bps=slippage_bps, funding_bps_per_bar=funding_bps_per_bar)
        return in_sample, out_sample
