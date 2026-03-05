from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

from packages.core.models import AccountState, MarketSnapshot, OrderRequest


@dataclass
class RiskResult:
    allowed: bool
    reason: str = "ok"
    reduce_only: bool = False


class RiskEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.safe_pause = False
        self.reduce_only_mode = False

    def evaluate_order(
        self,
        order: OrderRequest,
        account: AccountState,
        snapshots: Dict[str, MarketSnapshot],
    ) -> RiskResult:
        if self.safe_pause:
            return RiskResult(False, "safe_pause")
        if not account.known:
            return RiskResult(False, "unknown_account_state")
        if self._killswitch(account):
            self.safe_pause = True
            self.reduce_only_mode = True
            return RiskResult(False, "kill_switch_triggered", reduce_only=True)
        if self._exposure(account, snapshots) > self.cfg["max_total_exposure_notional"]:
            return RiskResult(False, "max_total_exposure")
        if len([p for p in account.positions.values() if abs(p.qty) > 0]) >= self.cfg["max_open_positions"]:
            if order.symbol not in account.positions or account.positions[order.symbol].qty == 0:
                return RiskResult(False, "max_open_positions")
        if account.leverage > self.cfg["max_leverage"]:
            return RiskResult(False, "leverage_cap")
        sym_cap = self.cfg["per_symbol_exposure_cap"].get(order.symbol)
        if sym_cap is not None and self._symbol_notional(order.symbol, account, snapshots) > sym_cap:
            return RiskResult(False, "per_symbol_cap")
        if self._correlation_block(order, account):
            return RiskResult(False, "correlation_cap")
        return RiskResult(True, "ok", reduce_only=self.reduce_only_mode)

    def _killswitch(self, account: AccountState) -> bool:
        return account.daily_pnl <= -abs(self.cfg["max_daily_loss"])

    def _exposure(self, account: AccountState, snapshots: Dict[str, MarketSnapshot]) -> float:
        total = 0.0
        for sym, pos in account.positions.items():
            px = snapshots.get(sym).price if snapshots.get(sym) else pos.entry_price
            total += abs(pos.qty * px)
        return total

    def _symbol_notional(self, symbol: str, account: AccountState, snapshots: Dict[str, MarketSnapshot]) -> float:
        pos = account.positions.get(symbol)
        if not pos:
            return 0.0
        px = snapshots.get(symbol).price if snapshots.get(symbol) else pos.entry_price
        return abs(pos.qty * px)

    def _correlation_block(self, order: OrderRequest, account: AccountState) -> bool:
        clusters: Dict[str, Iterable[str]] = self.cfg.get("correlation_clusters", {})
        for _, symbols in clusters.items():
            if order.symbol in symbols:
                long_count = 0
                short_count = 0
                for s in symbols:
                    qty = account.positions.get(s).qty if s in account.positions else 0
                    if qty > 0:
                        long_count += 1
                    elif qty < 0:
                        short_count += 1
                side_cap = self.cfg.get("correlation_direction_cap", 2)
                if order.side.upper() == "BUY" and long_count >= side_cap:
                    return True
                if order.side.upper() == "SELL" and short_count >= side_cap:
                    return True
        return False

    async def panic_flatten(self, account: AccountState, execution) -> None:
        await execution.cancel_all()
        for sym, pos in account.positions.items():
            if pos.qty == 0:
                continue
            side = "SELL" if pos.qty > 0 else "BUY"
            await execution.place_order(OrderRequest(symbol=sym, side=side, qty=abs(pos.qty), reduce_only=True))

    def trigger_safe_pause(self, reduce_only: bool = True) -> None:
        self.safe_pause = True
        if reduce_only:
            self.reduce_only_mode = True

    def clear_safe_pause(self) -> None:
        self.safe_pause = False
