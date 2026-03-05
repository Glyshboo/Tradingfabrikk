from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timezone
from typing import Any, Dict


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")


def log_event(event: str, payload: Dict[str, Any]) -> None:
    message = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    logging.getLogger("tradingfabrikk").info(json.dumps(message, ensure_ascii=False))


def write_status(path: str, status: Dict[str, Any]) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
