from packages.core.models import MarketSnapshot
from packages.execution.position_manager import PositionManager


def test_position_manager_trailing_and_time_stop():
    pm = PositionManager()
    pm.on_entry("BTCUSDT", "BUY", 0.01, 100.0, {"trail_mult": 1.0, "time_stop_bars": 2})
    pm.on_bar("BTCUSDT")
    assert pm.should_exit("BTCUSDT", MarketSnapshot("BTCUSDT", 102, 101.9, 102.1, atr=1.0)) is None
    pm.on_bar("BTCUSDT")
    assert pm.should_exit("BTCUSDT", MarketSnapshot("BTCUSDT", 101, 100.9, 101.1, atr=1.0)) in {"trailing_stop", "time_stop"}
