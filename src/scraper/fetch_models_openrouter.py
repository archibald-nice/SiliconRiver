"""Fetch model metadata from OpenRouter and persist into PostgreSQL."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Dict
from urllib.parse import quote

import psycopg
import requests
from dotenv import load_dotenv

try:
    from scripts.init_db import create_schema  # type: ignore
except Exception:  # pragma: no cover
    create_schema = None  # type: ignore

LOGGER = logging.getLogger("silicon_river.fetch.openrouter")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"
DEFAULT_DB_URL = "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/models"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(slots=True)
class ModelRecord:
    model_id: str
    provider: str
    model_name: str
    description: str
    created_at: str
    model_card_url: str
    inserted_at: str
    price: Optional[Dict[str, object]]
    is_open_source: Optional[bool]
    opencompass_rank: Optional[int]
    huggingface_rank: Optional[int]


def load_config() -> None:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False, encoding="utf-8-sig")


def resolve_db_url() -> str:
    load_config()
    return os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def get_providers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [provider.strip().lower() for provider in raw.split(",") if provider.strip()]


def ensure_db(url: str | None = None) -> psycopg.Connection:
    db_url = url or resolve_db_url()
    if create_schema is not None:
        create_schema(db_url)
    conn = psycopg.connect(db_url)
    return conn


def upsert_provider(
    conn: psycopg.Connection,
    provider_id: str,
    display_name: str | None = None,
    avatar_url: str | None = None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO providers (provider_id, display_name, avatar_url, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (provider_id) DO UPDATE
            SET
                display_name = EXCLUDED.display_name,
                avatar_url = COALESCE(EXCLUDED.avatar_url, providers.avatar_url),
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider_id, display_name or provider_id, avatar_url),
        )


def normalise_timestamp(epoch_seconds: int | float | None) -> str:
    if epoch_seconds is None:
        now = datetime.now(timezone.utc)
        return now.strftime(TIMESTAMP_FORMAT)
    dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return dt.strftime(TIMESTAMP_FORMAT)


def extract_provider(name: str | None, model_id: str | None = None) -> str:
    if not name:
        if model_id and "/" in model_id:
            return model_id.split("/", 1)[0].strip().lower() or "unknown"
        return "unknown"
    parts = name.split(":", 1)
    if parts:
        provider_raw = parts[0].strip()
        if provider_raw:
            return provider_raw.lower()
    stripped = name.strip()
    if stripped:
        return stripped.lower()
    if model_id and "/" in model_id:
        return model_id.split("/", 1)[0].strip().lower()
    return "unknown"


def to_record(raw: dict) -> ModelRecord:
    model_id = raw.get("id") or ""
    name = raw.get("name") or model_id
    provider = extract_provider(name, model_id)
    description = raw.get("description") or ""
    created = raw.get("created")
    created_at = normalise_timestamp(created if isinstance(created, (int, float)) else None)
    model_name = name
    inserted_at = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
    encoded_id = quote(model_id or name, safe="")
    model_card_url = f"https://openrouter.ai/models/{encoded_id}"
    pricing = raw.get("pricing")
    price_payload: Optional[Dict[str, object]] = pricing if isinstance(pricing, dict) and pricing else None
    if model_id and ":free" in model_id.lower():
        is_open_source = True
    else:
        is_open_source = False
    return ModelRecord(
        model_id=model_id or encoded_id,
        provider=provider or "unknown",
        model_name=model_name,
        description=description[:5000],
        created_at=created_at,
        model_card_url=model_card_url,
        inserted_at=inserted_at,
        price=price_payload,
        is_open_source=is_open_source,
        opencompass_rank=None,
        huggingface_rank=None,
    )


def save_models(conn: psycopg.Connection, provider: str, records: Iterable[ModelRecord]) -> tuple[int, int]:
    processed = 0
    inserted = 0
    with conn.cursor() as cursor:
        for record in records:
            processed += 1
            cursor.execute(
                """
                INSERT INTO models (
                    model_id, provider, model_name, description, tags,
                    created_at, downloads, likes, model_card_url, inserted_at,
                    price, is_open_source, opencompass_rank, huggingface_rank
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_id) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    model_name = EXCLUDED.model_name,
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags,
                    created_at = EXCLUDED.created_at,
                    model_card_url = EXCLUDED.model_card_url,
                    inserted_at = EXCLUDED.inserted_at,
                    price = COALESCE(EXCLUDED.price, models.price),
                    is_open_source = EXCLUDED.is_open_source,
                    opencompass_rank = COALESCE(EXCLUDED.opencompass_rank, models.opencompass_rank),
                    huggingface_rank = COALESCE(EXCLUDED.huggingface_rank, models.huggingface_rank)
                """,
                (
                    record.model_id,
                    provider,
                    record.model_name,
                    record.description,
                    json.dumps([], ensure_ascii=False),
                    record.created_at,
                    None,
                    None,
                    record.model_card_url,
                    record.inserted_at,
                    json.dumps(record.price, ensure_ascii=False) if record.price is not None else None,
                    record.is_open_source,
                    record.opencompass_rank,
                    record.huggingface_rank,
                ),
            )
            if cursor.rowcount:
                inserted += 1
    conn.commit()
    return processed, inserted


def fetch_remote_models(endpoint: str) -> List[dict]:
    LOGGER.info("Requesting OpenRouter models from %s", endpoint)
    response = requests.get(endpoint, timeout=30)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise ValueError("Unexpected response schema from OpenRouter.")
    LOGGER.info("Fetched %s models from OpenRouter", len(data))
    return data


def fetch_and_store(endpoint: str | None = None, *, limit: int | None = None) -> dict[str, tuple[int, int]]:
    load_config()
    endpoint_url = endpoint or os.getenv("OPENROUTER_MODELS_URL", DEFAULT_ENDPOINT)
    providers_filter = get_providers(os.getenv("PROVIDERS_OPENROUTER"))
    raw_models = fetch_remote_models(endpoint_url)
    if limit is not None and limit > 0:
        raw_models = raw_models[:limit]

    results: dict[str, tuple[int, int]] = {}
    with ensure_db() as conn:
        for item in raw_models:
            record = to_record(item)
            provider_key = record.provider
            provider_display = (item.get("name") or provider_key).split(":", 1)[0].strip()
            if not provider_display and record.model_id and "/" in record.model_id:
                provider_display = record.model_id.split("/", 1)[0].strip()
            provider_display = provider_display or provider_key
            if providers_filter and provider_key not in providers_filter:
                continue
            upsert_provider(conn, provider_id=provider_key, display_name=provider_display)
            processed, inserted = save_models(conn, provider_key, [record])
            existing = results.get(provider_key, (0, 0))
            results[provider_key] = (existing[0] + processed, existing[1] + inserted)
    return results


if __name__ == "__main__":
    summary = fetch_and_store()
    for provider, (processed, inserted) in summary.items():
        print(f"{provider}: processed={processed} inserted={inserted}")
