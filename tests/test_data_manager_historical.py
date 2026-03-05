from packages.data.data_manager import DataManager


def test_load_historical_prices_returns_expected_bars_and_is_deterministic():
    dm = DataManager(symbols=["BTCUSDT"])

    first = dm.load_historical_prices(symbol="BTCUSDT", regime="RANGE", bars=20)
    second = dm.load_historical_prices(symbol="BTCUSDT", regime="RANGE", bars=20)

    assert len(first) == 20
    assert first == second
    assert all(px > 0 for px in first)
