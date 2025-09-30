"""Fetch Hugging Face models and persist them into SQLite."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from dotenv import load_dotenv
from huggingface_hub import HfApi, ModelInfo

try:
    from scripts.init_db import create_schema  # type: ignore
except Exception:  # pragma: no cover
    create_schema = None  # type: ignore

LOGGER = logging.getLogger("silicon_river.fetch")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "silicon_river.db"
ENV_PATH = BASE_DIR / ".env"


@dataclass(slots=True)
class ModelRecord:
    model_id: str
    provider: str
    model_name: str
    description: str
    tags: List[str]
    created_at: str
    downloads: int | None
    likes: int | None
    model_card_url: str
    inserted_at: str


def load_config() -> None:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False)


def resolve_db_path() -> Path:
    load_config()
    url = os.getenv("DATABASE_URL")
    if url and url.startswith("sqlite:///"):
        return BASE_DIR / url.replace("sqlite:///", "")
    return DEFAULT_DB_PATH


def get_providers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [provider.strip() for provider in raw.split(",") if provider.strip()]


def hf_client() -> HfApi:
    load_config()
    token = os.getenv("HF_TOKEN")
    if not token:
        LOGGER.warning("HF_TOKEN is not set; unauthenticated requests may be rate-limited.")
    return HfApi(token=token)


def normalise_datetime(value: datetime | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def to_record(provider: str, info: ModelInfo) -> ModelRecord:
    card_data = getattr(info, "cardData", {}) or {}
    description = card_data.get("summary") or card_data.get("description") or ""
    fallback_description = getattr(info, "description", None)
    if not description and fallback_description:
        description = str(fallback_description)
    tags = list(getattr(info, "tags", []) or [])
    created_at = normalise_datetime(getattr(info, "created_at", None) or getattr(info, "lastModified", None))
    inserted_at = datetime.now(timezone.utc).isoformat()
    downloads = getattr(info, "downloads", None)
    likes = getattr(info, "likes", None)

    return ModelRecord(
        model_id=info.modelId,
        provider=provider,
        model_name=info.modelId.split("/")[-1],
        description=(description or "")[:300],
        tags=tags,
        created_at=created_at,
        downloads=downloads,
        likes=likes,
        model_card_url=f"https://huggingface.co/{info.modelId}",
        inserted_at=inserted_at,
    )


def ensure_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or resolve_db_path()
    if create_schema is not None:
        create_schema(db_path)
    else:  # pragma: no cover
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def save_models(conn: sqlite3.Connection, provider: str, records: Iterable[ModelRecord], *, started_at: datetime) -> tuple[int, int]:
    cursor = conn.cursor()
    processed = 0
    inserted = 0
    for record in records:
        processed += 1
        cursor.execute(
            """
            INSERT OR IGNORE INTO models (
                model_id, provider, model_name, description, tags,
                created_at, downloads, likes, model_card_url, inserted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.model_id,
                record.provider,
                record.model_name,
                record.description,
                json.dumps(record.tags, ensure_ascii=False),
                record.created_at,
                record.downloads,
                record.likes,
                record.model_card_url,
                record.inserted_at,
            ),
        )
        if cursor.rowcount:
            inserted += 1
    conn.commit()
    finished_at = datetime.now(timezone.utc)
    cursor.execute(
        """
        INSERT INTO sync_log (provider, started_at, finished_at, status, processed, inserted, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider,
            started_at.isoformat(),
            finished_at.isoformat(),
            "success",
            processed,
            inserted,
            None,
        ),
    )
    conn.commit()
    return processed, inserted


def fetch_and_store(limit: int = 50) -> dict[str, tuple[int, int]]:
    client = hf_client()
    providers = get_providers(os.getenv("PROVIDERS"))
    if not providers:
        raise RuntimeError("PROVIDERS is not configured. Set it in environment or .env file.")

    results: dict[str, tuple[int, int]] = {}
    with ensure_db() as conn:
        for provider in providers:
            LOGGER.info("Fetching models for provider %s", provider)
            models_iter = client.list_models(
                author=provider,
                sort="lastModified",
                direction=-1,
                limit=limit,
                full=True,
            )
            started_at = datetime.now(timezone.utc)
            records = (to_record(provider, info) for info in models_iter)
            processed, inserted = save_models(conn, provider, records, started_at=started_at)
            LOGGER.info("Provider %s: processed=%s inserted=%s", provider, processed, inserted)
            results[provider] = (processed, inserted)
    return results


if __name__ == "__main__":
    summary = fetch_and_store()
    for provider, (processed, inserted) in summary.items():
        print(f"{provider}: processed={processed} inserted={inserted}")
