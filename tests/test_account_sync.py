import json
import time

from packages.data.data_manager import DataManager


def test_user_stream_account_update_sets_equity_and_positions():
    dm = DataManager(["BTCUSDT"])
    dm._ingest_user_message(
        json.dumps(
            {
                "e": "ACCOUNT_UPDATE",
                "a": {
                    "B": [{"a": "USDT", "wb": "1234.5", "cw": "1200"}],
                    "P": [{"s": "BTCUSDT", "pa": "0.02", "ep": "50000"}],
                },
            }
        )
    )
    assert dm.account_state["equity"] == 1234.5
    assert dm.account_state["positions"]["BTCUSDT"]["qty"] == 0.02


def test_paper_fill_updates_local_position_conservatively():
    dm = DataManager(["BTCUSDT"])
    dm.apply_paper_fill("BTCUSDT", "BUY", 0.01, 100)
    dm.apply_paper_fill("BTCUSDT", "SELL", 0.01, 101, reduce_only=True)
    assert dm.account_state["positions"]["BTCUSDT"]["qty"] == 0.0


def test_account_sync_health_requires_fresh_event_when_requested():
    dm = DataManager(["BTCUSDT"])
    dm.user_stream_alive = True
    dm.account_state["last_event_ts"] = time.time() - 999

    assert dm.is_account_sync_healthy(max_age_sec=5, require_event=True) is False
