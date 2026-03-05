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
    view = {
        "mode": status.get("mode"),
        "state": status.get("state"),
        "symbols": status.get("symbols", []),
        "open_positions": status.get("open_positions", {}),
        "last_decision": status.get("last_decision"),
        "ws_status": status.get("ws_status", {}),
        "risk_caps_status": status.get("risk_caps_status", {}),
        "safe_pause": status.get("safe_pause"),
        "reduce_only": status.get("reduce_only"),
        "ts": status.get("ts"),
    }
    print(json.dumps(view, indent=2))


if __name__ == "__main__":
    main()
