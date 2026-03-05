import time

from packages.core.models import AccountState, OrderRequest
from packages.data.data_manager import DataManager
from packages.risk.engine import RiskEngine


def _risk_cfg():
    return {
        "max_daily_loss": 100,
        "max_total_exposure_notional": 10000,
        "max_leverage": 5,
        "max_open_positions": 5,
        "per_symbol_exposure_cap": {},
    }


def test_data_manager_health_fail_closed_on_user_stream_down():
    dm = DataManager(["BTCUSDT"], stale_after_sec=10)
    dm.last_update_ts = time.time()
    dm.user_stream_alive = False
    assert dm.is_healthy() is False


def test_data_manager_health_fail_closed_without_market_updates():
    dm = DataManager(["BTCUSDT"], stale_after_sec=10)
    dm.user_stream_alive = True
    dm.market_stream_alive = True

    assert dm.is_healthy() is False


def test_stream_health_market_age_none_before_first_tick():
    dm = DataManager(["BTCUSDT"], stale_after_sec=10)
    dm.user_stream_alive = True
    dm.market_stream_alive = True

    health = dm.stream_health()

    assert health["market_fresh"] is False
    assert health["market_age_sec"] is None


def test_trigger_safe_pause_enables_reduce_only_mode():
    risk = RiskEngine(_risk_cfg())
    risk.trigger_safe_pause()
    rr = risk.evaluate_order(
        OrderRequest(symbol="BTCUSDT", side="BUY", qty=1),
        AccountState(equity=1000, daily_pnl=0, positions={}, leverage=1, known=True),
        {},
    )
    assert rr.allowed is False
    assert rr.reason == "safe_pause"
    assert risk.reduce_only_mode is True
