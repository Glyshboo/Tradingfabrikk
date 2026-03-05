from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Dict, Iterable
from urllib import parse, request

import websockets

from packages.core.models import MarketSnapshot
from packages.telemetry.logging_utils import log_event


class DataManager:
    def __init__(
        self,
        symbols: Iterable[str],
        stale_after_sec: int = 20,
        api_key: str | None = None,
        rest_base_url: str = "https://fapi.binance.com",
        ws_base_url: str = "wss://fstream.binance.com",
        require_user_stream_auth: bool = False,
    ):
        self.symbols = [s.upper().replace("/", "") for s in symbols]
        self.market: Dict[str, MarketSnapshot] = {}
        self.last_update_ts: float | None = None
        self.stale_after_sec = stale_after_sec
        self.user_stream_alive = False
        self.market_stream_alive = False
        self._market_reconnect_delay_sec = 1
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_base_url = ws_base_url.rstrip("/")
        self.require_user_stream_auth = require_user_stream_auth

    async def run_market_stream(self) -> None:
        url = self._market_stream_url()
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                    self.market_stream_alive = True
                    self._market_reconnect_delay_sec = 1
                    async for message in ws:
                        now = time.time()
                        self._ingest_market_message(message, now)
                        self.last_update_ts = now
            except Exception as exc:
                self.market_stream_alive = False
                log_event(
                    "market_stream_drop",
                    {
                        "error": str(exc),
                        "reconnect_in_sec": self._market_reconnect_delay_sec,
                        "proxy_env_present": bool(os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")),
                    },
                )
                await asyncio.sleep(self._market_reconnect_delay_sec)
                self._market_reconnect_delay_sec = min(30, self._market_reconnect_delay_sec * 2)

    async def run_user_stream(self) -> None:
        if not self.api_key and not self.require_user_stream_auth:
            self.user_stream_alive = True
            while True:
                await asyncio.sleep(5)

        while True:
            if not self.api_key:
                self.user_stream_alive = False
                log_event("user_stream_auth_missing", {"require_user_stream_auth": self.require_user_stream_auth})
                await asyncio.sleep(2)
                continue
            listen_key = await asyncio.to_thread(self._create_listen_key)
            if not listen_key:
                self.user_stream_alive = False
                await asyncio.sleep(2)
                continue
            keepalive_task = asyncio.create_task(self._keepalive_listen_key(listen_key))
            ws_url = f"{self.ws_base_url}/ws/{listen_key}"
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                    self.user_stream_alive = True
                    async for _ in ws:
                        self.user_stream_alive = True
            except Exception as exc:
                self.user_stream_alive = False
                log_event("user_stream_drop", {"error": str(exc)})
            finally:
                keepalive_task.cancel()
                await asyncio.gather(keepalive_task, return_exceptions=True)

    def _ingest_market_message(self, message: str, now: float) -> None:
        payload = json.loads(message)
        data = payload.get("data", payload)
        symbol = str(data.get("s", "")).upper()
        if symbol not in self.symbols:
            return
        bid = float(data.get("b", data.get("c", 0.0)))
        ask = float(data.get("a", data.get("c", 0.0)))
        price = (bid + ask) / 2 if bid and ask else float(data.get("c", 0.0))
        prev = self.market.get(symbol)
        self.market[symbol] = MarketSnapshot(
            symbol=symbol,
            price=price,
            bid=bid if bid else price,
            ask=ask if ask else price,
            candle_close=price,
            atr=prev.atr if prev else None,
            rsi=prev.rsi if prev else None,
            ts=now,
        )

    def _market_stream_url(self) -> str:
        streams = "/".join(f"{s.lower()}@bookTicker" for s in self.symbols)
        return f"{self.ws_base_url}/stream?streams={streams}"

    def _create_listen_key(self) -> str | None:
        req = request.Request(
            url=f"{self.rest_base_url}/fapi/v1/listenKey",
            method="POST",
            headers={"X-MBX-APIKEY": self.api_key},
            data=b"",
        )
        try:
            with request.urlopen(req, timeout=4.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("listenKey")
        except Exception as exc:
            log_event("user_stream_listenkey_error", {"error": str(exc)})
            return None

    async def _keepalive_listen_key(self, listen_key: str) -> None:
        while True:
            await asyncio.sleep(30 * 60)
            await asyncio.to_thread(self._renew_listen_key, listen_key)

    def _renew_listen_key(self, listen_key: str) -> None:
        data = parse.urlencode({"listenKey": listen_key}).encode("utf-8")
        req = request.Request(
            url=f"{self.rest_base_url}/fapi/v1/listenKey",
            method="PUT",
            headers={"X-MBX-APIKEY": self.api_key, "Content-Type": "application/x-www-form-urlencoded"},
            data=data,
        )
        try:
            request.urlopen(req, timeout=4.0).close()
        except Exception as exc:
            self.user_stream_alive = False
            log_event("user_stream_keepalive_error", {"error": str(exc)})

    def get_snapshot(self, symbol: str) -> MarketSnapshot | None:
        return self.market.get(symbol.upper().replace("/", ""))

    def is_healthy(self) -> bool:
        if not self.user_stream_alive:
            return False
        if not self.market_stream_alive:
            return False
        if self.last_update_ts is None:
            return False
        if time.time() - self.last_update_ts > self.stale_after_sec:
            return False
        return True

    def stream_health(self) -> Dict[str, float | bool | None]:
        market_age_sec = None if self.last_update_ts is None else max(0.0, time.time() - self.last_update_ts)
        return {
            "market_stream_alive": self.market_stream_alive,
            "market_fresh": market_age_sec is not None and market_age_sec <= self.stale_after_sec,
            "market_age_sec": market_age_sec,
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
