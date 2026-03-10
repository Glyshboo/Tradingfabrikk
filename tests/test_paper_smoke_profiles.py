from __future__ import annotations

from packages.backtest.engine import BacktestResult
from packages.research.candidate_registry import CandidateRegistry
from packages.review.paper_smoke import PaperSmokeWorker


def test_paper_smoke_uses_stricter_threshold_for_new_family(tmp_path, monkeypatch):
    reg = CandidateRegistry(str(tmp_path / "registry.json"))
    reg.register(
        "cand_new",
        1.0,
        {
            "symbols": ["BTCUSDT"],
            "regimes": ["RANGE"],
            "strategy_family": "TrendCore",
            "candidate_kind": "new_family_candidate",
            "config_patch": {"TrendCore": {}},
        },
    )
    reg.transition("cand_new", "paper_smoke_running")

    cfg = {
        "symbols": ["BTCUSDT"],
        "paper_smoke": {"bars": 20, "min_trades": 2, "min_pnl": -1.0},
        "paper_smoke_profiles": {"new_family_candidate": {"min_trades": 5, "min_pnl": 0.5}},
    }
    worker = PaperSmokeWorker(reg, cfg)
    monkeypatch.setattr(worker._dm, "load_historical_candles", lambda **kwargs: [{"close": 1}] * 12)
    monkeypatch.setattr(worker.bt, "run", lambda *args, **kwargs: BacktestResult(trades=3, pnl=0.3, sharpe_like=0.2, gross_pnl=0.6, total_cost=0.3, max_drawdown=0.2, turnover=10))

    actions = worker.process()
    assert actions[0]["result"]["status"] == "fail"
    assert actions[0]["result"]["required_min_trades"] == 5
