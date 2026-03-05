import asyncio

import pytest

from packages.core.models import OrderRequest
from packages.execution.adapters import BinanceRequestError, LiveExecutionAdapter


class _FakeAdapter(LiveExecutionAdapter):
    def __init__(self, responses):
        super().__init__(api_key="k", api_secret="s", retries=1)
        self._responses = list(responses)

    def _request_once(self, method, url, encoded, headers):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_place_order_maps_fields_for_binance():
    adapter = _FakeAdapter(
        responses=[
            (
                {"symbol": "BTCUSDT", "side": "BUY", "status": "NEW"},
                {
                    "x-mbx-used-weight-1m": "2",
                    "x-mbx-order-count-10s": "1",
                    "x-mbx-order-count-1m": "1",
                },
            )
        ]
    )
    out = asyncio.run(adapter.place_order(OrderRequest(symbol="btc/usdt", side="buy", qty=0.01)))
    assert out["symbol"] == "BTCUSDT"
    assert out["side"] == "BUY"
    assert out["qty"] == 0.01
    assert out["mode"] == "live"


def test_retries_on_server_errors_then_succeeds():
    adapter = _FakeAdapter(
        responses=[
            BinanceRequestError("server", "temporary", status_code=500, retryable=True),
            ({"symbol": "BTCUSDT", "side": "BUY", "status": "NEW"}, {}),
        ]
    )
    out = asyncio.run(adapter.place_order(OrderRequest(symbol="BTCUSDT", side="BUY", qty=0.05)))
    assert out["status"] == "NEW"


@pytest.mark.parametrize(
    "error",
    [
        BinanceRequestError("client", "bad request", status_code=400),
        BinanceRequestError("auth", "forbidden", status_code=401),
        BinanceRequestError("rate_limit", "too many requests", status_code=429),
        BinanceRequestError("timeout", "timeout", retryable=True),
    ],
)
def test_place_order_raises_for_4xx_rate_limit_timeout(error):
    adapter = _FakeAdapter(responses=[error, error])
    with pytest.raises(BinanceRequestError):
        asyncio.run(adapter.place_order(OrderRequest(symbol="BTCUSDT", side="BUY", qty=0.01)))



def test_cancel_all_calls_signed_delete():
    adapter = _FakeAdapter(responses=[({}, {})])
    asyncio.run(adapter.cancel_all("ethusdt"))
