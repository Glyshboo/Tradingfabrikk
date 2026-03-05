from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import Optional

from packages.core.models import DecisionRecord


class AuditStore:
    def __init__(self, db_path: str = "runtime/audit.db") -> None:
        self.path = pathlib.Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                regime TEXT,
                eligible_strategies TEXT,
                score_breakdown TEXT,
                selected_strategy TEXT,
                selected_config TEXT,
                sizing TEXT,
                blocked_reason TEXT
            )
            """
        )
        self.conn.commit()

    def save_decision(self, rec: DecisionRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO decisions(symbol, regime, eligible_strategies, score_breakdown,
            selected_strategy, selected_config, sizing, blocked_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.symbol,
                rec.regime,
                json.dumps(rec.eligible_strategies),
                json.dumps(rec.score_breakdown),
                rec.selected_strategy,
                rec.selected_config,
                json.dumps(rec.sizing),
                rec.blocked_reason,
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
