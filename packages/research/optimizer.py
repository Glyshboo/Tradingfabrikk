from __future__ import annotations

import json
import pathlib
import random
from typing import Dict, List

from packages.backtest.engine import CandleBacktester


class ResearchOptimizer:
    def __init__(self, out_dir: str = "configs/candidates") -> None:
        self.out_dir = pathlib.Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def random_search(self, search_space: Dict, samples: int = 10) -> List[Dict]:
        results = []
        bt = CandleBacktester()
        prices = [100 + i * 0.1 + ((-1) ** i) * 0.05 for i in range(400)]
        for i in range(samples):
            cfg = {
                "atr_stop_mult": random.choice(search_space["atr_stop_mult"]),
                "time_stop_bars": random.choice(search_space["time_stop_bars"]),
                "base_confidence": random.choice(search_space["base_confidence"]),
            }
            res = bt.run(prices, fee_bps=4, slippage_bps=2)
            score = res.sharpe_like + cfg["base_confidence"] - (cfg["atr_stop_mult"] * 0.01)
            payload = {"id": f"candidate_{i}", "config": cfg, "score": round(score, 6), "pnl": res.pnl}
            results.append(payload)
            (self.out_dir / f"candidate_{i}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        results.sort(key=lambda x: x["score"], reverse=True)
        (self.out_dir / "ranking.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        return results
