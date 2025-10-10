"""Initialize PostgreSQL schema for the Silicon River project."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import psycopg
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

DEFAULT_DB_URL = os.getenv("DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river")

MODEL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS models (
    id BIGSERIAL PRIMARY KEY,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    description TEXT,
    tags TEXT,
    created_at TEXT NOT NULL,
    downloads BIGINT,
    likes BIGINT,
    model_card_url TEXT NOT NULL,
    inserted_at TEXT NOT NULL,
    UNIQUE (model_id)
);
"""

SYNC_LOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sync_log (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    processed BIGINT NOT NULL DEFAULT 0,
    inserted BIGINT NOT NULL DEFAULT 0,
    error_message TEXT
);
"""

MODEL_TAGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model_tags (
    id BIGSERIAL PRIMARY KEY,
    model_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    inserted_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (model_id, tag),
    FOREIGN KEY (model_id) REFERENCES models(model_id) ON DELETE CASCADE
);
"""

INDICES_SQL: Iterable[str] = (
    "CREATE INDEX IF NOT EXISTS idx_models_provider_created_at ON models(provider, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_models_inserted_at ON models(inserted_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sync_log_provider_started_at ON sync_log(provider, started_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_model_tags_tag ON model_tags(tag);",
    "CREATE INDEX IF NOT EXISTS idx_model_tags_model_id ON model_tags(model_id);",
)


def create_schema(db_url: str | None = None) -> None:
    """Create required tables and indexes if they do not exist."""
    db_url = db_url or DEFAULT_DB_URL
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute(MODEL_TABLE_SQL)
            cursor.execute(SYNC_LOG_TABLE_SQL)
            cursor.execute(MODEL_TAGS_TABLE_SQL)
            for statement in INDICES_SQL:
                cursor.execute(statement)


if __name__ == "__main__":
    create_schema()
    print("PostgreSQL schema ready.")
