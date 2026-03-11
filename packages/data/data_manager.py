from __future__ import annotations

import asyncio
import json
import math
import os
import pathlib
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from json import JSONDecodeError
from typing import Any, Dict, Iterable
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
        cache_dir: str = "runtime/data_cache",
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
        self._user_stream_disabled_logged = False
        self.cache_dir = pathlib.Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.candles: dict[str, dict[str, deque[dict[str, float | bool]]]] = {
            sym: {"1h": deque(maxlen=1200), "4h": deque(maxlen=1200)} for sym in self.symbols
        }
        self._active_candles: dict[str, dict[str, dict[str, float | bool]]] = defaultdict(dict)
        self._indicators: dict[str, dict[str, dict[str, float | None]]] = {
            sym: {
                "1h": {"atr": None, "rsi": None, "trend_slope": None, "realized_volatility": None, "range_compression_score": None, "range_high": None, "range_low": None, "breakout_distance_from_recent_range": None},
                "4h": {"atr": None, "rsi": None, "trend_slope": None, "realized_volatility": None, "range_compression_score": None, "range_high": None, "range_low": None, "breakout_distance_from_recent_range": None},
            }
            for sym in self.symbols
        }
        self.account_state: dict[str, Any] = {"equity": None, "positions": {}, "last_event_ts": None}

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
        if not self.require_user_stream_auth:
            self.user_stream_alive = True
            if not self._user_stream_disabled_logged:
                log_event("user_stream_disabled", {"reason": "paper_mode_auth_not_required"})
                self._user_stream_disabled_logged = True
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
                    async for message in ws:
                        self.user_stream_alive = True
                        self._ingest_user_message(message)
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

        if data.get("e") == "kline" and data.get("k"):
            self._ingest_kline(symbol, data["k"])
            return

        bid = float(data.get("b", data.get("c", 0.0)))
        ask = float(data.get("a", data.get("c", 0.0)))
        price = (bid + ask) / 2 if bid and ask else float(data.get("c", 0.0))
        prev = self.market.get(symbol)
        next_bid = bid if bid else price
        next_ask = ask if ask else price
        spread_bps = ((next_ask - next_bid) / max(price, 1e-9)) * 10000
        self.market[symbol] = MarketSnapshot(
            symbol=symbol,
            price=price,
            bid=next_bid,
            ask=next_ask,
            candle_close=prev.candle_close if prev else price,
            atr=prev.atr if prev else None,
            rsi=prev.rsi if prev else None,
            trend_slope=prev.trend_slope if prev else None,
            realized_volatility=prev.realized_volatility if prev else None,
            spread_bps=round(spread_bps, 6),
            atr_pct_of_price=prev.atr_pct_of_price if prev else None,
            session_bucket=prev.session_bucket if prev else None,
            hour_bucket=prev.hour_bucket if prev else None,
            range_compression_score=prev.range_compression_score if prev else None,
            breakout_distance_from_recent_range=prev.breakout_distance_from_recent_range if prev else None,
            rsi_1h=prev.rsi_1h if prev else None,
            rsi_4h=prev.rsi_4h if prev else None,
            atr_1h=prev.atr_1h if prev else None,
            atr_4h=prev.atr_4h if prev else None,
            ts=now,
        )

    def _ingest_kline(self, symbol: str, kline: dict[str, Any]) -> None:
        interval = str(kline.get("i", ""))
        if interval not in {"1h", "4h"}:
            return
        candle = {
            "open_time": float(kline.get("t", 0.0)),
            "close_time": float(kline.get("T", 0.0)),
            "open": float(kline.get("o", 0.0)),
            "high": float(kline.get("h", 0.0)),
            "low": float(kline.get("l", 0.0)),
            "close": float(kline.get("c", 0.0)),
            "closed": bool(kline.get("x", False)),
        }
        self._active_candles[symbol][interval] = candle
        if candle["closed"]:
            self._append_closed_candle(symbol, interval, candle)
            self._recompute_interval_features(symbol, interval)

        indicators_1h = self._indicators[symbol]["1h"]
        indicators_4h = self._indicators[symbol]["4h"]
        atr_1h = indicators_1h.get("atr")
        atr_4h = indicators_4h.get("atr")
        rsi_1h = indicators_1h.get("rsi")
        rsi_4h = indicators_4h.get("rsi")
        atr = atr_1h if atr_1h is not None else atr_4h
        rsi = rsi_1h if rsi_1h is not None else rsi_4h
        trend_slope = indicators_1h.get("trend_slope") if indicators_1h.get("trend_slope") is not None else indicators_4h.get("trend_slope")
        realized_volatility = indicators_1h.get("realized_volatility") if indicators_1h.get("realized_volatility") is not None else indicators_4h.get("realized_volatility")
        range_compression_score = indicators_1h.get("range_compression_score") if indicators_1h.get("range_compression_score") is not None else indicators_4h.get("range_compression_score")
        breakout_distance = indicators_1h.get("breakout_distance_from_recent_range") if indicators_1h.get("breakout_distance_from_recent_range") is not None else indicators_4h.get("breakout_distance_from_recent_range")
        prev = self.market.get(symbol)
        base_bid = prev.bid if prev else candle["close"]
        base_ask = prev.ask if prev else candle["close"]
        spread_bps = ((base_ask - base_bid) / max(candle["close"], 1e-9)) * 10000
        hour_bucket = self._extract_hour_bucket(candle)
        self.market[symbol] = MarketSnapshot(
            symbol=symbol,
            price=candle["close"],
            bid=base_bid,
            ask=base_ask,
            candle_close=candle["close"],
            atr=atr,
            rsi=rsi,
            trend_slope=trend_slope,
            realized_volatility=realized_volatility,
            spread_bps=round(spread_bps, 6),
            atr_pct_of_price=(None if atr is None else round(atr / max(candle["close"], 1e-9), 8)),
            session_bucket=self._session_bucket_for_hour(hour_bucket),
            hour_bucket=hour_bucket,
            range_compression_score=range_compression_score,
            breakout_distance_from_recent_range=breakout_distance,
            rsi_1h=rsi_1h,
            rsi_4h=rsi_4h,
            atr_1h=atr_1h,
            atr_4h=atr_4h,
            ts=time.time(),
        )

    def _append_closed_candle(self, symbol: str, interval: str, candle: dict[str, float | bool]) -> None:
        series = self.candles[symbol][interval]
        if series and series[-1]["open_time"] == candle["open_time"]:
            series[-1] = candle
        else:
            series.append(candle)

    def _compute_atr(self, symbol: str, interval: str, period: int) -> float | None:
        candles = list(self.candles[symbol][interval])
        if len(candles) < period + 1:
            return None
        true_ranges: list[float] = []
        for i in range(1, len(candles)):
            curr = candles[i]
            prev_close = float(candles[i - 1]["close"])
            high = float(curr["high"])
            low = float(curr["low"])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        if len(true_ranges) < period:
            return None
        return round(sum(true_ranges[-period:]) / period, 8)

    def _compute_rsi(self, symbol: str, interval: str, period: int) -> float | None:
        candles = list(self.candles[symbol][interval])
        if len(candles) < period + 1:
            return None
        closes = [float(c["close"]) for c in candles]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss <= 1e-12:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 6)

    def _compute_trend_slope(self, symbol: str, interval: str, lookback: int = 20) -> float | None:
        candles = list(self.candles[symbol][interval])
        if len(candles) < lookback:
            return None
        closes = [float(c["close"]) for c in candles[-lookback:]]
        first = closes[0]
        if first <= 1e-9:
            return None
        slope = (closes[-1] - first) / first
        return round(slope, 8)

    def _compute_realized_volatility(self, symbol: str, interval: str, lookback: int = 20) -> float | None:
        candles = list(self.candles[symbol][interval])
        if len(candles) < lookback + 1:
            return None
        closes = [float(c["close"]) for c in candles[-(lookback + 1):]]
        log_returns: list[float] = []
        for prev, curr in zip(closes[:-1], closes[1:]):
            if prev <= 1e-9 or curr <= 1e-9:
                continue
            log_returns.append(math.log(curr / prev))
        if len(log_returns) < 2:
            return None
        mean = sum(log_returns) / len(log_returns)
        variance = sum((x - mean) ** 2 for x in log_returns) / (len(log_returns) - 1)
        return round(math.sqrt(max(variance, 0.0)), 8)

    def _compute_recent_range_metrics(self, symbol: str, interval: str, lookback: int = 20) -> tuple[float | None, float | None, float | None, float | None]:
        candles = list(self.candles[symbol][interval])
        if len(candles) < lookback:
            return None, None, None, None
        window = candles[-lookback:]
        highs = [float(c["high"]) for c in window]
        lows = [float(c["low"]) for c in window]
        closes = [float(c["close"]) for c in window]
        range_high = max(highs)
        range_low = min(lows)
        width = max(range_high - range_low, 0.0)
        avg_close = sum(closes) / len(closes)
        compression = None if avg_close <= 1e-9 else round(width / avg_close, 8)
        last_close = closes[-1]
        distance = 0.0
        if last_close > range_high:
            distance = (last_close - range_high) / max(last_close, 1e-9)
        elif last_close < range_low:
            distance = (last_close - range_low) / max(last_close, 1e-9)
        return round(range_high, 8), round(range_low, 8), compression, round(distance, 8)

    def _extract_hour_bucket(self, candle: dict[str, float | bool]) -> int:
        close_time_ms = float(candle.get("close_time", 0.0) or 0.0)
        if close_time_ms <= 0:
            return int(datetime.now(timezone.utc).hour)
        return int(datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc).hour)

    def _session_bucket_for_hour(self, hour_bucket: int) -> str:
        if 0 <= hour_bucket < 8:
            return "asia"
        if 8 <= hour_bucket < 16:
            return "europe"
        return "us"

    def _recompute_interval_features(self, symbol: str, interval: str) -> None:
        range_high, range_low, compression, breakout_distance = self._compute_recent_range_metrics(symbol, interval, lookback=20)
        self._indicators[symbol][interval] = {
            "atr": self._compute_atr(symbol, interval, 14),
            "rsi": self._compute_rsi(symbol, interval, 14),
            "trend_slope": self._compute_trend_slope(symbol, interval, lookback=20),
            "realized_volatility": self._compute_realized_volatility(symbol, interval, lookback=20),
            "range_compression_score": compression,
            "range_high": range_high,
            "range_low": range_low,
            "breakout_distance_from_recent_range": breakout_distance,
        }

    def _market_stream_url(self) -> str:
        streams = [f"{s.lower()}@bookTicker" for s in self.symbols]
        for s in self.symbols:
            streams.append(f"{s.lower()}@kline_1h")
            streams.append(f"{s.lower()}@kline_4h")
        return f"{self.ws_base_url}/stream?streams={'/'.join(streams)}"

    def _ingest_user_message(self, message: str) -> None:
        payload = json.loads(message)
        payload = payload.get("data", payload)
        evt = payload.get("e")
        if evt == "ACCOUNT_UPDATE":
            account = payload.get("a", {})
            balances = account.get("B", [])
            usdt = next((b for b in balances if b.get("a") == "USDT"), None)
            if usdt:
                wb = float(usdt.get("wb", 0.0))
                cw = float(usdt.get("cw", wb))
                self.account_state["equity"] = max(wb, cw)
            positions = {}
            for p in account.get("P", []):
                symbol = str(p.get("s", "")).upper()
                if symbol in self.symbols:
                    qty = float(p.get("pa", 0.0))
                    positions[symbol] = {"qty": qty, "entry_price": float(p.get("ep", 0.0))}
            for symbol in self.symbols:
                self.account_state["positions"][symbol] = positions.get(symbol, {"qty": 0.0, "entry_price": 0.0})
            self.account_state["last_event_ts"] = time.time()
        elif evt == "ORDER_TRADE_UPDATE":
            order = payload.get("o", {})
            symbol = str(order.get("s", "")).upper()
            if symbol in self.symbols:
                last_fill_qty = float(order.get("l", 0.0) or 0.0)
                last_fill_price = float(order.get("L", 0.0) or order.get("ap", 0.0) or 0.0)
                side = str(order.get("S", "")).upper()
                reduce_only = bool(order.get("R", False))
                if last_fill_qty > 0 and last_fill_price > 0 and side in {"BUY", "SELL"}:
                    self.apply_paper_fill(symbol, side, last_fill_qty, last_fill_price, reduce_only=reduce_only)
            self.account_state["last_event_ts"] = time.time()

    def apply_paper_fill(self, symbol: str, side: str, qty: float, fill_price: float, reduce_only: bool = False) -> None:
        symbol = symbol.upper().replace("/", "")
        pos = self.account_state["positions"].get(symbol, {"qty": 0.0, "entry_price": 0.0})
        signed_qty = qty if side.upper() == "BUY" else -qty
        existing_qty = float(pos.get("qty", 0.0))
        new_qty = existing_qty + signed_qty
        if reduce_only and (existing_qty == 0 or math.copysign(1.0, existing_qty) == math.copysign(1.0, new_qty) and abs(new_qty) > abs(existing_qty)):
            return
        if abs(new_qty) < 1e-12:
            self.account_state["positions"][symbol] = {"qty": 0.0, "entry_price": 0.0}
        elif existing_qty == 0 or math.copysign(1.0, existing_qty) != math.copysign(1.0, new_qty):
            self.account_state["positions"][symbol] = {"qty": new_qty, "entry_price": fill_price}
        else:
            weighted = ((abs(existing_qty) * pos.get("entry_price", 0.0)) + (abs(signed_qty) * fill_price)) / max(abs(new_qty), 1e-12)
            self.account_state["positions"][symbol] = {"qty": new_qty, "entry_price": weighted}
        self.account_state["last_event_ts"] = time.time()

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

    def reconcile_live_account_state(self) -> bool:
        if not self.api_key:
            return False
        req = request.Request(
            url=f"{self.rest_base_url}/fapi/v2/account",
            method="GET",
            headers={"X-MBX-APIKEY": self.api_key},
        )
        try:
            with request.urlopen(req, timeout=6.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            wallet = float(payload.get("totalWalletBalance", 0.0) or 0.0)
            cross_wallet = float(payload.get("totalCrossWalletBalance", 0.0) or wallet)
            self.account_state["equity"] = max(wallet, cross_wallet)
            positions = {}
            for row in payload.get("positions", []):
                symbol = str(row.get("symbol", "")).upper()
                if symbol not in self.symbols:
                    continue
                positions[symbol] = {
                    "qty": float(row.get("positionAmt", 0.0) or 0.0),
                    "entry_price": float(row.get("entryPrice", 0.0) or 0.0),
                }
            for symbol in self.symbols:
                self.account_state["positions"][symbol] = positions.get(symbol, {"qty": 0.0, "entry_price": 0.0})
            self.account_state["last_event_ts"] = time.time()
            return True
        except Exception as exc:
            log_event("account_reconcile_error", {"error": str(exc)})
            return False

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
            "account_last_event_age_sec": None
            if self.account_state.get("last_event_ts") is None
            else max(0.0, time.time() - float(self.account_state["last_event_ts"])),
        }


    def persist_state(self, path: str = "runtime/data_state.json") -> None:
        payload = {
            "account_state": self.account_state,
            "candles": {
                sym: {interval: list(series) for interval, series in rows.items()}
                for sym, rows in self.candles.items()
            },
            "last_update_ts": self.last_update_ts,
        }
        pathlib.Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_state(self, path: str = "runtime/data_state.json") -> None:
        state_file = pathlib.Path(path)
        if not state_file.exists():
            return
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except JSONDecodeError:
            log_event("runtime_json_invalid", {"file": str(state_file), "fallback": "empty_data_state"})
            return
        except OSError as exc:
            log_event("runtime_json_read_error", {"file": str(state_file), "error": str(exc), "fallback": "empty_data_state"})
            return
        if not isinstance(payload, dict):
            log_event("runtime_json_invalid", {"file": str(state_file), "fallback": "empty_data_state"})
            return
        self.account_state.update(payload.get("account_state", {}))
        for sym, rows in payload.get("candles", {}).items():
            if sym in self.candles:
                for interval, series in rows.items():
                    if interval in self.candles[sym]:
                        self.candles[sym][interval].clear()
                        self.candles[sym][interval].extend(series)
        self.last_update_ts = payload.get("last_update_ts")
        for sym in self.symbols:
            for interval in ("1h", "4h"):
                self._recompute_interval_features(sym, interval)

    def backfill_gap(self, downtime_sec: float) -> None:
        if downtime_sec <= 0:
            return
        now_ms = int(time.time() * 1000)
        start_ms = int((time.time() - downtime_sec - 4 * 3600) * 1000)
        for symbol in self.symbols:
            for interval in ("1h", "4h"):
                klines = self._download_klines(symbol, interval=interval, start_ts=start_ms, end_ts=now_ms, limit=500)
                for row in klines:
                    candle = {
                        "open_time": float(row[0]),
                        "close_time": float(row[6] if len(row) > 6 else row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "closed": True,
                    }
                    self._append_closed_candle(symbol, interval, candle)
                self._recompute_interval_features(symbol, interval)
    def load_historical_candles(
        self,
        symbol: str,
        regime: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        bars: int = 400,
        interval: str = "1h",
    ) -> list[dict[str, float]]:
        symbol = symbol.upper().replace("/", "")
        if symbol not in self.symbols or bars < 3:
            return []

        cache_file = self.cache_dir / f"{symbol}_{interval}_{start_ts or 0}_{end_ts or 0}_{bars}.json"
        if cache_file.exists():
            try:
                payload = json.loads(cache_file.read_text(encoding="utf-8"))
            except (JSONDecodeError, OSError) as exc:
                log_event("historical_cache_invalid", {"file": str(cache_file), "error": str(exc), "action": "redownload"})
                payload = self._download_klines(symbol, interval=interval, start_ts=start_ts, end_ts=end_ts, limit=bars)
                if not payload:
                    return []
                cache_file.write_text(json.dumps(payload), encoding="utf-8")
        else:
            payload = self._download_klines(symbol, interval=interval, start_ts=start_ts, end_ts=end_ts, limit=bars)
            if not payload:
                log_event(
                    "historical_klines_unavailable",
                    {"symbol": symbol, "interval": interval, "start_ts": start_ts, "end_ts": end_ts, "bars": bars, "regime": regime},
                )
                return []
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
        candles = []
        for row in payload:
            candles.append({
                "open_time": float(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "close_time": float(row[6] if len(row) > 6 else row[0]),
            })
        return candles

    def load_historical_prices(
        self,
        symbol: str,
        regime: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        bars: int = 400,
        interval: str = "1h",
    ) -> list[float]:
        candles = self.load_historical_candles(symbol, regime, start_ts=start_ts, end_ts=end_ts, bars=bars, interval=interval)
        return [float(r["close"]) for r in candles]

    def _download_klines(
        self,
        symbol: str,
        interval: str = "1h",
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 400,
    ) -> list[list[Any]]:
        q = {"symbol": symbol, "interval": interval, "limit": min(1500, max(3, limit))}
        if start_ts:
            q["startTime"] = int(start_ts)
        if end_ts:
            q["endTime"] = int(end_ts)
        url = f"{self.rest_base_url}/fapi/v1/klines?{parse.urlencode(q)}"
        try:
            with request.urlopen(url, timeout=6.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if isinstance(payload, list):
                    return payload
        except Exception as exc:
            log_event("historical_klines_error", {"symbol": symbol, "interval": interval, "error": str(exc)})
        return []
