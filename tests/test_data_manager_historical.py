from packages.data.data_manager import DataManager


def test_load_historical_prices_uses_cache(tmp_path):
    dm = DataManager(symbols=["BTCUSDT"], cache_dir=str(tmp_path))

    fake_rows = [[0, "1", "2", "0.5", "1.5"], [1, "1.5", "2.5", "1", "2"]]
    dm._download_klines = lambda *args, **kwargs: fake_rows

    first = dm.load_historical_prices(symbol="BTCUSDT", regime="RANGE", bars=5)
    second = dm.load_historical_prices(symbol="BTCUSDT", regime="RANGE", bars=5)

    assert first == [1.5, 2.0]
    assert second == first
    assert len(list(tmp_path.glob("*.json"))) == 1
