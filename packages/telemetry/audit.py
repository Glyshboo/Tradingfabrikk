from __future__ import annotations

import json
import pathlib
import sqlite3

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
                selected_candidate TEXT,
                selected_strategy TEXT,
                selected_config TEXT,
                side TEXT,
                qty REAL,
                sizing TEXT,
                caps_status TEXT,
                blocked_reason TEXT
            )
            """
        )
        existing = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(decisions)").fetchall()
        }
        if "selected_candidate" not in existing:
            self.conn.execute("ALTER TABLE decisions ADD COLUMN selected_candidate TEXT")
        if "side" not in existing:
            self.conn.execute("ALTER TABLE decisions ADD COLUMN side TEXT")
        if "qty" not in existing:
            self.conn.execute("ALTER TABLE decisions ADD COLUMN qty REAL")
        if "caps_status" not in existing:
            self.conn.execute("ALTER TABLE decisions ADD COLUMN caps_status TEXT")
        self.conn.commit()

    def save_decision(self, rec: DecisionRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO decisions(symbol, regime, eligible_strategies, score_breakdown,
            selected_candidate, selected_strategy, selected_config, side, qty, sizing, caps_status, blocked_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.symbol,
                rec.regime,
                json.dumps(rec.eligible_strategies),
                json.dumps(rec.score_breakdown),
                rec.selected_candidate,
                rec.selected_strategy,
                rec.selected_config,
                rec.side,
                rec.qty,
                json.dumps(rec.sizing),
                json.dumps(rec.caps_status),
                rec.blocked_reason,
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
