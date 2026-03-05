from __future__ import annotations

import asyncio
import random
import time
from typing import Dict, Iterable

from packages.core.models import MarketSnapshot


class DataManager:
    def __init__(self, symbols: Iterable[str], stale_after_sec: int = 20):
        self.symbols = list(symbols)
        self.market: Dict[str, MarketSnapshot] = {}
        self.last_update_ts: float = 0.0
        self.stale_after_sec = stale_after_sec
        self.user_stream_alive = False

    async def run_market_stream(self) -> None:
        # MVP stub for websocket-driven flow. Replace with real Binance stream adapter.
        base = {s: 100.0 + i * 10 for i, s in enumerate(self.symbols)}
        while True:
            now = time.time()
            for s in self.symbols:
                drift = random.uniform(-0.5, 0.5)
                base[s] += drift
                bid = base[s] - 0.02
                ask = base[s] + 0.02
                self.market[s] = MarketSnapshot(
                    symbol=s,
                    price=base[s],
                    bid=bid,
                    ask=ask,
                    candle_close=base[s],
                    atr=abs(drift) + 0.3,
                    rsi=50 + random.uniform(-15, 15),
                    ts=now,
                )
            self.last_update_ts = now
            await asyncio.sleep(1)

    async def run_user_stream(self) -> None:
        while True:
            self.user_stream_alive = True
            await asyncio.sleep(5)

    def get_snapshot(self, symbol: str) -> MarketSnapshot | None:
        return self.market.get(symbol)

    def is_healthy(self) -> bool:
        if not self.user_stream_alive:
            return False
        if time.time() - self.last_update_ts > self.stale_after_sec:
            return False
        return True

    def stream_health(self) -> Dict[str, float | bool]:
        return {
            "market_fresh": (time.time() - self.last_update_ts) <= self.stale_after_sec,
            "market_age_sec": max(0.0, time.time() - self.last_update_ts),
            "user_stream_alive": self.user_stream_alive,
            "stale_after_sec": self.stale_after_sec,
        }

    def load_historical_prices(
        self,
        symbol: str,
        regime: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        bars: int = 400,
    ) -> list[float]:
        if symbol not in self.symbols:
            return []
        if bars < 3:
            return []

        seed = hash((symbol, regime, start_ts, end_ts)) & 0xFFFFFFFF
        rng = random.Random(seed)
        base_price = 100.0 + (abs(hash(symbol)) % 200)
        regime_drift = {
            "TREND_UP": 0.18,
            "TREND_DOWN": -0.18,
            "RANGE": 0.0,
        }.get(regime, 0.0)

        prices = [base_price]
        for _ in range(1, bars):
            drift = regime_drift + rng.uniform(-0.12, 0.12)
            next_px = max(0.1, prices[-1] + drift)
            prices.append(next_px)
        return prices
