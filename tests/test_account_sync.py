import json

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


def test_user_stream_account_update_clears_missing_symbol_positions():
    dm = DataManager(["BTCUSDT", "ETHUSDT"])
    dm.account_state["positions"] = {
        "BTCUSDT": {"qty": 0.02, "entry_price": 50000.0},
        "ETHUSDT": {"qty": 1.0, "entry_price": 3000.0},
    }
    dm._ingest_user_message(
        json.dumps(
            {
                "e": "ACCOUNT_UPDATE",
                "a": {
                    "B": [{"a": "USDT", "wb": "1000", "cw": "1000"}],
                    "P": [{"s": "BTCUSDT", "pa": "0.02", "ep": "50000"}],
                },
            }
        )
    )
    assert dm.account_state["positions"]["ETHUSDT"]["qty"] == 0.0


def test_order_trade_update_updates_position_with_fill_delta():
    dm = DataManager(["BTCUSDT"])
    dm._ingest_user_message(
        json.dumps({"e": "ORDER_TRADE_UPDATE", "o": {"s": "BTCUSDT", "S": "BUY", "l": "0.01", "L": "50000", "R": False}})
    )
    assert dm.account_state["positions"]["BTCUSDT"]["qty"] == 0.01


def test_paper_fill_updates_local_position_conservatively():
    dm = DataManager(["BTCUSDT"])
    dm.apply_paper_fill("BTCUSDT", "BUY", 0.01, 100)
    dm.apply_paper_fill("BTCUSDT", "SELL", 0.01, 101, reduce_only=True)
    assert dm.account_state["positions"]["BTCUSDT"]["qty"] == 0.0
