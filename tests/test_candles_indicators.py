import json

from packages.data.data_manager import DataManager


def _kline(close: float, t: int, closed: bool = True):
    return json.dumps({"data": {"e": "kline", "s": "BTCUSDT", "k": {"i": "1h", "t": t, "T": t + 1, "o": close - 1, "h": close + 1, "l": close - 2, "c": close, "x": closed}}})


def test_kline_buffer_computes_indicators_after_enough_candles():
    dm = DataManager(["BTCUSDT"])
    for i in range(20):
        dm._ingest_market_message(_kline(100 + i, i), now=1_000 + i)
    snap = dm.get_snapshot("BTCUSDT")
    assert snap is not None
    assert snap.atr is not None
    assert snap.rsi is not None


def test_open_kline_updates_price_but_does_not_append_closed_history():
    dm = DataManager(["BTCUSDT"])
    for i in range(15):
        dm._ingest_market_message(_kline(100 + i, i, closed=True), now=1_000 + i)
    baseline_len = len(dm.candles["BTCUSDT"]["1h"])
    dm._ingest_market_message(_kline(130, 9_999, closed=False), now=2_000)
    assert len(dm.candles["BTCUSDT"]["1h"]) == baseline_len
    snap = dm.get_snapshot("BTCUSDT")
    assert snap is not None
    assert snap.price == 130
