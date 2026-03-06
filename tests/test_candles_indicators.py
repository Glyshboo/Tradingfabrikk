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
