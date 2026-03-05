from packages.core.models import AccountState, OrderRequest, PositionState
from packages.risk.engine import RiskEngine


def _cfg():
    return {
        "max_daily_loss": 100,
        "max_total_exposure_notional": 10000,
        "max_leverage": 5,
        "max_open_positions": 5,
        "per_symbol_exposure_cap": {"BTCUSDT": 6000},
        "correlation_clusters": {"c1": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]},
        "correlation_direction_cap": 2,
    }


def test_kill_switch_trigger():
    risk = RiskEngine(_cfg())
    account = AccountState(equity=1000, daily_pnl=-120, positions={}, leverage=1, known=True)
    rr = risk.evaluate_order(OrderRequest(symbol="BTCUSDT", side="BUY", qty=1), account, {})
    assert not rr.allowed
    assert rr.reason == "kill_switch_triggered"


def test_correlation_cap_blocks_third_long():
    risk = RiskEngine(_cfg())
    account = AccountState(
        equity=1000,
        daily_pnl=0,
        positions={
            "BTCUSDT": PositionState("BTCUSDT", qty=1),
            "ETHUSDT": PositionState("ETHUSDT", qty=1),
            "SOLUSDT": PositionState("SOLUSDT", qty=0),
        },
        leverage=1,
        known=True,
    )
    rr = risk.evaluate_order(OrderRequest(symbol="SOLUSDT", side="BUY", qty=1), account, {})
    assert not rr.allowed
    assert rr.reason == "correlation_cap"
