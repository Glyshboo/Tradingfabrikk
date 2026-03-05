from __future__ import annotations

import argparse
import asyncio
import json

from packages.core.config import load_config
from packages.core.models import AccountState, OrderRequest, PositionState
from packages.execution.adapters import PaperExecutionAdapter
from packages.risk.engine import RiskEngine


async def run_self_check(config_path: str) -> dict:
    cfg = load_config(config_path)

    risk_daily_loss = RiskEngine(cfg["risk"])
    daily_loss_account = AccountState(
        equity=cfg["account"]["equity"],
        daily_pnl=-abs(cfg["risk"]["max_daily_loss"]) - 1,
        positions={},
        leverage=1.0,
        known=True,
    )
    daily_loss_result = risk_daily_loss.evaluate_order(
        OrderRequest(symbol=cfg["symbols"][0], side="BUY", qty=cfg["sizing"]["base_qty"]),
        daily_loss_account,
        {},
    )

    risk_exposure = RiskEngine(cfg["risk"])
    exposure_symbol = cfg["symbols"][0]
    exposure_cap = cfg["risk"]["max_total_exposure_notional"]
    exposure_account = AccountState(
        equity=cfg["account"]["equity"],
        daily_pnl=0,
        positions={
            exposure_symbol: PositionState(
                symbol=exposure_symbol,
                qty=1.0,
                entry_price=exposure_cap + 100,
            )
        },
        leverage=1.0,
        known=True,
    )
    exposure_result = risk_exposure.evaluate_order(
        OrderRequest(symbol=exposure_symbol, side="BUY", qty=cfg["sizing"]["base_qty"]),
        exposure_account,
        {},
    )

    risk_flatten = RiskEngine(cfg["risk"])
    execution = PaperExecutionAdapter()
    flatten_account = AccountState(
        equity=cfg["account"]["equity"],
        daily_pnl=0,
        positions={
            cfg["symbols"][0]: PositionState(symbol=cfg["symbols"][0], qty=0.4, entry_price=100),
            cfg["symbols"][1]: PositionState(symbol=cfg["symbols"][1], qty=-0.7, entry_price=100),
        },
        leverage=1.0,
        known=True,
    )
    await risk_flatten.panic_flatten(flatten_account, execution)

    return {
        "daily_loss_cap": {"allowed": daily_loss_result.allowed, "reason": daily_loss_result.reason},
        "max_exposure_cap": {"allowed": exposure_result.allowed, "reason": exposure_result.reason},
        "panic_flatten": {
            "cancel_and_reduce_only_orders": len(execution.orders),
            "orders": execution.orders,
        },
        "expected": {
            "daily_loss_cap_reason": "kill_switch_triggered",
            "max_exposure_cap_reason": "max_total_exposure",
            "panic_flatten_reduce_only": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    args = parser.parse_args()
    output = asyncio.run(run_self_check(args.config))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
