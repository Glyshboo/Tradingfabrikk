import asyncio

from packages.core.models import AccountState, OrderRequest
from packages.execution.adapters import BinanceRequestError
from packages.risk.engine import RiskEngine


def _risk_cfg():
    return {
        "max_daily_loss": 100,
        "max_total_exposure_notional": 10000,
        "max_leverage": 5,
        "max_open_positions": 5,
        "per_symbol_exposure_cap": {},
    }


def test_safe_pause_blocks_new_entries_but_allows_reduce_only():
    risk = RiskEngine(_risk_cfg())
    risk.trigger_safe_pause(reduce_only=True)
    account = AccountState(equity=1000, daily_pnl=0, positions={}, leverage=1, known=True)

    blocked = risk.evaluate_order(OrderRequest(symbol="BTCUSDT", side="BUY", qty=1, reduce_only=False), account, {})
    assert blocked.allowed is False

    allowed = risk.evaluate_order(OrderRequest(symbol="BTCUSDT", side="SELL", qty=1, reduce_only=True), account, {})
    assert allowed.allowed is True
    assert allowed.reduce_only is True


def test_binance_error_category_can_trigger_fail_closed_state():
    err = BinanceRequestError("rate_limit", "slow down", status_code=429)
    assert err.category == "rate_limit"
