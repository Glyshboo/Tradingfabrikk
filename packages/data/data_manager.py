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
