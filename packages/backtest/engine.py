from __future__ import annotations

from dataclasses import dataclass
from typing import List

from packages.core.models import MarketSnapshot, Regime, StrategyContext
from packages.selector.regime_engine import RegimeEngine
from packages.strategies.composition import build_strategy_evaluator
from packages.strategies.entry_families import (
    BreakoutRetestEntryFamily,
    EntryFamilyStrategyPlugin,
    FailedBreakoutFadeEntryFamily,
    TrendPullbackEntryFamily,
)
from packages.strategies.range_mr import RangeMR
from packages.strategies.trend_core import TrendCore


@dataclass
class BacktestResult:
    trades: int
    pnl: float
    sharpe_like: float
    gross_pnl: float = 0.0
    total_cost: float = 0.0
    max_drawdown: float = 0.0
    turnover: float = 0.0


class CandleBacktester:
    def __init__(self) -> None:
        self.regime_engine = RegimeEngine()
        self.strategies = {
            "TrendCore": TrendCore(),
            "RangeMR": RangeMR(),
            "BreakoutRetest": EntryFamilyStrategyPlugin(
                BreakoutRetestEntryFamily(), {Regime.TREND_UP, Regime.TREND_DOWN, Regime.HIGH_VOL}
            ),
            "TrendPullback": EntryFamilyStrategyPlugin(TrendPullbackEntryFamily(), {Regime.TREND_UP, Regime.TREND_DOWN}),
            "FailedBreakoutFade": EntryFamilyStrategyPlugin(
                FailedBreakoutFadeEntryFamily(), {Regime.RANGE, Regime.HIGH_VOL, Regime.TREND_UP, Regime.TREND_DOWN}
            ),
        }
        self.strategy_evaluator = build_strategy_evaluator(self.strategies)

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

    def _compute_trend_slope(self, candles: list[dict], i: int, lookback: int = 12) -> float | None:
        if i < lookback:
            return None
        close_now = float(candles[i]["close"])
        close_prev = float(candles[i - lookback]["close"])
        if close_prev <= 0:
            return None
        return (close_now - close_prev) / close_prev / float(lookback)

    def _compute_breakout_distance(self, candles: list[dict], i: int, window: int = 20, atr: float | None = None) -> float | None:
        if i < window or atr is None or atr <= 0:
            return None
        segment = candles[i - window : i]
        recent_high = max(float(c["high"]) for c in segment)
        recent_low = min(float(c["low"]) for c in segment)
        close_now = float(candles[i]["close"])
        if close_now > recent_high:
            return (close_now - recent_high) / atr
        if close_now < recent_low:
            return (close_now - recent_low) / atr
        return 0.0

    def _compute_range_compression(self, candles: list[dict], i: int, short_window: int = 8, long_window: int = 32) -> float | None:
        if i < long_window:
            return None
        short_seg = candles[i - short_window + 1 : i + 1]
        long_seg = candles[i - long_window + 1 : i + 1]
        short_range = sum(float(c["high"]) - float(c["low"]) for c in short_seg) / float(short_window)
        long_range = sum(float(c["high"]) - float(c["low"]) for c in long_seg) / float(long_window)
        if long_range <= 1e-12:
            return 0.0
        ratio = short_range / long_range
        return max(0.0, min(1.0, 1.0 - ratio))

    def _snapshot_for_bar(self, candles: list[dict], i: int, strategy_config: dict | None = None) -> MarketSnapshot:
        close = float(candles[i]["close"])
        cfg = strategy_config or {}
        atr_period = int(cfg.get("atr_period", 14))
        rsi_period = int(cfg.get("rsi_period", 14))
        # Backtest bruker candle-close syntetisk spread=0 for deterministisk signalparitet.
        atr = self._compute_atr(candles, i, period=max(2, atr_period))
        return MarketSnapshot(
            symbol="BACKTEST",
            price=close,
            bid=close,
            ask=close,
            candle_close=float(candles[i - 1]["close"]) if i > 0 else close,
            atr=atr,
            rsi=self._compute_rsi(candles, i, period=max(2, rsi_period)),
            trend_slope=self._compute_trend_slope(candles, i),
            breakout_distance_from_recent_range=self._compute_breakout_distance(candles, i, atr=atr),
            range_compression_score=self._compute_range_compression(candles, i),
            ts=float(i),
        )

    def _signal_for_bar(self, strategy_family: str, candles: list[dict], i: int, strategy_config: dict | None = None) -> int:
        snapshot = self._snapshot_for_bar(candles, i, strategy_config=strategy_config)
        regime = self.regime_engine.classify(snapshot)
        return self.signal_for_snapshot(strategy_family, snapshot, regime, strategy_config)

    def signal_for_snapshot(
        self,
        strategy_family: str,
        snapshot: MarketSnapshot,
        regime: Regime,
        strategy_config: dict | None = None,
    ) -> int:
        if strategy_family not in self.strategies:
            return 0
        signal = self.strategy_evaluator.evaluate(
            strategy_family,
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
        gross_pnl = 0.0
        total_cost = 0.0
        trades = 0
        turnover = 0.0
        equity = 0.0
        peak_equity = 0.0
        max_drawdown = 0.0
        costs_bps = (fee_bps + slippage_bps + funding_bps_per_bar) / 10000

        position = 0.0
        signal_meta: dict = {}
        bars_open = 0
        peak_price = 0.0
        partial_taken = False

        for i in range(2, len(candles)):
            snap_prev = self._snapshot_for_bar(candles, i - 1, strategy_config=strategy_config)
            close_now = float(candles[i]["close"])
            close_prev = float(candles[i - 1]["close"])
            ret = 0.0 if close_prev <= 0 else (close_now - close_prev) / close_prev

            if position != 0:
                gross_leg = position * ret * close_now
                cost_leg = close_now * costs_bps
                gross_pnl += gross_leg
                total_cost += cost_leg
                pnl += gross_leg - cost_leg
                trades += 1
                turnover += abs(position) * close_now
                bars_open += 1
                if position > 0:
                    peak_price = max(peak_price, close_now)
                else:
                    peak_price = min(peak_price, close_now)

                stop_price = signal_meta.get("stop_price")
                take_profit = signal_meta.get("take_profit")
                partial_take = signal_meta.get("partial_take_profit")
                exit_pack = signal_meta.get("exit_pack", "passthrough")
                trail_mult = float(signal_meta.get("trail_mult", 0.0) or 0.0)
                time_stop_bars = int(signal_meta.get("time_stop_bars", 0) or 0)
                atr = snap_prev.atr or 0.0

                should_close = False
                if position > 0:
                    if stop_price is not None and close_now <= float(stop_price):
                        should_close = True
                    elif take_profit is not None and close_now >= float(take_profit):
                        should_close = True
                    elif partial_take is not None and (not partial_taken) and close_now >= float(partial_take):
                        partial_taken = True
                        fraction = float(signal_meta.get("partial_fraction", 0.5))
                        fraction = max(0.0, min(1.0, fraction))
                        position = position * (1.0 - fraction)
                    elif atr > 0 and trail_mult > 0 and exit_pack in {"atr_trail", "partial_tp_runner"}:
                        trail = peak_price - atr * trail_mult
                        if trail > 0 and close_now <= trail:
                            should_close = True
                else:
                    if stop_price is not None and close_now >= float(stop_price):
                        should_close = True
                    elif take_profit is not None and close_now <= float(take_profit):
                        should_close = True
                    elif partial_take is not None and (not partial_taken) and close_now <= float(partial_take):
                        partial_taken = True
                        fraction = float(signal_meta.get("partial_fraction", 0.5))
                        fraction = max(0.0, min(1.0, fraction))
                        position = position * (1.0 - fraction)
                    elif atr > 0 and trail_mult > 0 and exit_pack in {"atr_trail", "partial_tp_runner"}:
                        trail = peak_price + atr * trail_mult
                        if trail > 0 and close_now >= trail:
                            should_close = True

                if time_stop_bars > 0 and bars_open >= time_stop_bars:
                    should_close = True

                if should_close:
                    position = 0.0
                    signal_meta = {}
                    bars_open = 0
                    peak_price = 0.0
                    partial_taken = False

            if position == 0:
                regime = self.regime_engine.classify(snap_prev)
                signal = self.strategy_evaluator.evaluate(
                    strategy_family,
                    StrategyContext(snapshot=snap_prev, regime=regime, config=strategy_config or {}),
                )
                if signal:
                    position = 1.0 if signal.side == "BUY" else -1.0 if signal.side == "SELL" else 0.0
                    if position != 0:
                        signal_meta = {
                            "stop_price": signal.stop_price,
                            "take_profit": signal.take_profit,
                            "time_stop_bars": signal.meta.get("time_stop_bars", 0),
                            "trail_mult": signal.meta.get("trail_mult", 0.0),
                            "exit_pack": signal.meta.get("exit_pack", "passthrough"),
                            "partial_take_profit": signal.meta.get("partial_take_profit"),
                            "partial_fraction": signal.meta.get("partial_fraction", 0.0),
                        }
                        bars_open = 0
                        peak_price = close_now
                        partial_taken = False

            equity = pnl
            if equity > peak_equity:
                peak_equity = equity
            drawdown = peak_equity - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        sharpe_like = pnl / max(1.0, trades**0.5)
        return BacktestResult(
            trades=trades,
            pnl=round(pnl, 6),
            sharpe_like=round(sharpe_like, 6),
            gross_pnl=round(gross_pnl, 6),
            total_cost=round(total_cost, 6),
            max_drawdown=round(max_drawdown, 6),
            turnover=round(turnover, 6),
        )

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
