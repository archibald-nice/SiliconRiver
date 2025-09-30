"""Initialize SQLite schema for the Silicon River project."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

DEFAULT_DB_PATH = Path("data/silicon_river.db")

MODEL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    description TEXT,
    tags TEXT,
    created_at TEXT NOT NULL,
    downloads INTEGER,
    likes INTEGER,
    model_card_url TEXT NOT NULL,
    inserted_at TEXT NOT NULL,
    UNIQUE(model_id)
);
"""

SYNC_LOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);
"""

INDICES_SQL: Iterable[str] = (
    "CREATE INDEX IF NOT EXISTS idx_models_provider_created_at ON models(provider, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_models_inserted_at ON models(inserted_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sync_log_provider_started_at ON sync_log(provider, started_at DESC);",
)


def create_schema(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Create required tables and indexes if they do not exist."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(MODEL_TABLE_SQL)
        cursor.execute(SYNC_LOG_TABLE_SQL)
        for statement in INDICES_SQL:
            cursor.execute(statement)
        conn.commit()


if __name__ == "__main__":
    create_schema()
    print(f"SQLite schema ready at {DEFAULT_DB_PATH.resolve()}")
