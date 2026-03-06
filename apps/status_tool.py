from __future__ import annotations

import argparse
import json
import pathlib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", default="runtime/status.json")
    args = parser.parse_args()

    p = pathlib.Path(args.status_file)
    if not p.exists():
        print("No status file found")
        return
    status = json.loads(p.read_text(encoding="utf-8"))
    last_decision = status.get("last_decision") or {}
    decision_view = {
        "symbol": last_decision.get("symbol"),
        "regime": last_decision.get("regime"),
        "eligible_strategies": last_decision.get("eligible_strategies", []),
        "score_breakdown": last_decision.get("score_breakdown", {}),
        "selected_candidate": last_decision.get("selected_candidate"),
        "side": last_decision.get("side"),
        "qty": last_decision.get("qty"),
        "blocked_reason": last_decision.get("blocked_reason"),
        "caps_status": last_decision.get("caps_status", {}),
    }

    view = {
        "mode": status.get("mode"),
        "state": status.get("state"),
        "symbols": status.get("symbols", []),
        "open_positions": status.get("open_positions", {}),
        "last_decision": decision_view,
        "ws_status": status.get("ws_status", {}),
        "account_sync_health": status.get("account_sync_health", {}),
        "current_regime": status.get("current_regime", {}),
        "risk_caps_status": status.get("risk_caps_status", {}),
        "safe_pause": status.get("safe_pause"),
        "reduce_only": status.get("reduce_only"),
        "ts": status.get("ts"),
    }
    print(json.dumps(view, indent=2))


if __name__ == "__main__":
    main()
