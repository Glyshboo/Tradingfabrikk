from __future__ import annotations

import argparse
import asyncio

from packages.core.config import load_config
from packages.core.master_engine import MasterEngine
from packages.execution.adapters import LiveExecutionAdapter
from packages.telemetry.logging_utils import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if cfg.get("mode") != "live":
        raise SystemExit("Refusing to start live runner unless mode=live in config (fail-closed).")
    setup_logging(cfg.get("logging", {}).get("level", "INFO"))
    engine = MasterEngine(cfg, LiveExecutionAdapter())
    asyncio.run(engine.run())


if __name__ == "__main__":
    main()
