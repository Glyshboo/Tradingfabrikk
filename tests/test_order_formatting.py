from packages.execution.adapters import format_order


def test_order_formatting_qty_floor():
    o = format_order("BTCUSDT", "BUY", -1)
    assert o.qty == 0
    assert o.side == "BUY"
