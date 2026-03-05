def test_simple_sizing_formula():
    base_qty = 0.01
    confidence = 0.6
    qty = max(0.0, base_qty * confidence)
    assert qty == 0.006
