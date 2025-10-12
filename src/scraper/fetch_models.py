"""Fetch Hugging Face models and persist them into PostgreSQL."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Dict

import psycopg
import requests
from dotenv import load_dotenv
from huggingface_hub import HfApi, ModelInfo
from huggingface_hub.utils import HfHubHTTPError
from html.parser import HTMLParser
from urllib.parse import urljoin

try:
    from scripts.init_db import create_schema  # type: ignore
except Exception:  # pragma: no cover
    create_schema = None  # type: ignore

LOGGER = logging.getLogger("silicon_river.fetch")
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOGGING_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"
DEFAULT_DB_URL = "postgresql://USER:PASSWORD@HOST:5432/silicon_river"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HTTP_TIMEOUT = 15
AVATAR_MAX_BYTES = int(os.getenv("AVATAR_MAX_BYTES", "524288"))


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
    is_open_source: Optional[bool]
    price: Optional[Dict[str, object]]
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
    return [provider.strip() for provider in raw.split(",") if provider.strip()]


def hf_client() -> HfApi:
    load_config()
    token = os.getenv("HF_TOKEN")
    if not token:
        LOGGER.warning("HF_TOKEN is not set; unauthenticated requests may be rate-limited.")
    return HfApi(token=token)


def normalise_datetime(value: datetime | None) -> datetime:
    if value is None:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_timestamp(value: datetime | None) -> str:
    return normalise_datetime(value).strftime(TIMESTAMP_FORMAT)


def to_record(provider: str, info: ModelInfo) -> ModelRecord:
    card_data = getattr(info, "cardData", {}) or {}
    description = card_data.get("summary") or card_data.get("description") or ""
    fallback_description = getattr(info, "description", None)
    if not description and fallback_description:
        description = str(fallback_description)
    tags = list(getattr(info, "tags", []) or [])
    created_at = format_timestamp(getattr(info, "created_at", None) or getattr(info, "lastModified", None))
    inserted_at = format_timestamp(datetime.now(timezone.utc))
    downloads = getattr(info, "downloads", None)
    likes = getattr(info, "likes", None)
    private_attr = getattr(info, "private", None)
    if private_attr is None:
        is_open_source = None
    else:
        is_open_source = True if private_attr is None else not bool(private_attr)

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
        is_open_source=is_open_source,
        price=None,
        opencompass_rank=None,
        huggingface_rank=None,
    )


def ensure_db(url: str | None = None) -> psycopg.Connection:
    db_url = url or resolve_db_url()
    if create_schema is not None:
        create_schema(db_url)
    conn = psycopg.connect(db_url)
    return conn


def upsert_provider(
    conn: psycopg.Connection,
    provider_id: str,
    avatar_url: str | None,
    display_name: str | None,
    avatar_content: bytes | None,
    avatar_mime: str | None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO providers (provider_id, display_name, avatar_url, avatar_blob, avatar_mime, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (provider_id) DO UPDATE
            SET
                display_name = EXCLUDED.display_name,
                avatar_url = EXCLUDED.avatar_url,
                avatar_blob = EXCLUDED.avatar_blob,
                avatar_mime = EXCLUDED.avatar_mime,
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider_id, display_name, avatar_url, avatar_content, avatar_mime),
        )


def _extract_display_name(info: object, provider_id: str) -> str:
    candidates = ("displayName", "fullname", "name")
    if isinstance(info, dict):
        for key in candidates:
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value
        nested = info.get("organization") or info.get("user")
        if isinstance(nested, dict):
            for key in candidates:
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return info.get("id") or info.get("uid") or provider_id
    for attr in candidates:
        value = getattr(info, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return getattr(info, "id", provider_id)


def _extract_avatar_url(info: object) -> str | None:
    candidates = ("avatarUrl", "avatar_url", "avatar")
    if isinstance(info, dict):
        for key in candidates:
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value
        nested = info.get("organization") or info.get("user")
        if isinstance(nested, dict):
            for key in candidates:
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None
    for attr in candidates:
        value = getattr(info, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def resolve_provider_profile(client: HfApi, provider_id: str) -> tuple[str, str | None]:
    resolver_groups = (
        ("organization_info", "get_org"),
        ("user_info", "get_user"),
    )
    for resolver_names in resolver_groups:
        resolver = None
        resolver_name = None
        for name in resolver_names:
            if hasattr(client, name):
                resolver = getattr(client, name)
                resolver_name = name
                break
        if resolver is None or resolver_name is None:
            continue
        try:
            info = resolver(provider_id)
        except HfHubHTTPError as error:
            if getattr(error, "response", None) is not None and error.response.status_code == 404:
                continue
            LOGGER.warning("Failed to fetch %s for %s: %s", resolver_name, provider_id, error)
            continue
        except Exception as exc:  # pragma: no cover - unexpected
            LOGGER.warning("Unexpected error calling %s for %s: %s", resolver_name, provider_id, exc)
            continue
        info_object = info.dict() if hasattr(info, "dict") else info
        display_name = _extract_display_name(info_object, provider_id)
        avatar_url = _extract_avatar_url(info_object)
        if avatar_url is None:
            LOGGER.debug("Provider %s missing avatar in %s payload: %s", provider_id, resolver_name, info_object)
        return display_name, avatar_url
    token = os.getenv("HF_TOKEN")
    display_name, avatar_url = fetch_provider_profile_http(provider_id, token)
    return display_name, avatar_url


def _http_get_json(url: str, token: str | None) -> dict | None:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        LOGGER.debug("HTTP metadata request failed %s: %s", url, exc)
        return None
    if response.status_code == 404:
        return None
    if not response.ok:
        LOGGER.debug("HTTP metadata request %s returned %s: %s", url, response.status_code, response.text)
        return None
    try:
        return response.json()
    except ValueError:
        LOGGER.debug("HTTP metadata response from %s is not JSON", url)
        return None


def fetch_provider_profile_http(provider_id: str, token: str | None) -> tuple[str, str | None]:
    endpoints = (
        f"https://huggingface.co/api/organizations/{provider_id}",
        f"https://huggingface.co/api/users/{provider_id}",
    )
    for url in endpoints:
        payload = _http_get_json(url, token)
        if not payload:
            continue
        display_name = _extract_display_name(payload, provider_id)
        avatar_url = _extract_avatar_url(payload)
        if avatar_url or display_name != provider_id:
            return display_name, avatar_url
    display_name, avatar_url = fetch_provider_profile_html(provider_id)
    return display_name, avatar_url


def download_provider_avatar(avatar_url: str | None, token: str | None) -> tuple[bytes | None, str | None]:
    if not avatar_url:
        return None, None
    headers = {"Accept": "image/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(avatar_url, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        LOGGER.debug("Avatar download failed %s: %s", avatar_url, exc)
        return None, None
    if not response.ok:
        LOGGER.debug("Avatar download %s returned %s", avatar_url, response.status_code)
        return None, None
    content = response.content
    if len(content) > AVATAR_MAX_BYTES:
        LOGGER.debug("Avatar %s exceeds max bytes (%s)", avatar_url, AVATAR_MAX_BYTES)
        return None, None
    content_type = response.headers.get("content-type")
    if content_type:
        content_type = content_type.split(";")[0].strip()
    return content, content_type


class _ProfileHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self._h1_active = False
        self.heading: list[str] = []
        self.img_candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value for key, value in attrs if value is not None}
        if tag == "meta":
            prop = attrs_dict.get("property")
            content = attrs_dict.get("content")
            if prop in {"og:image", "og:title"} and content:
                self.meta[prop] = content
        elif tag == "h1":
            self._h1_active = True
        elif tag == "img":
            src = attrs_dict.get("src")
            if src:
                classes = attrs_dict.get("class", "")
                if any(keyword in classes for keyword in ("object-cover", "avatar", "rounded-full")):
                    self.img_candidates.append(src)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._h1_active = False

    def handle_data(self, data: str) -> None:
        if self._h1_active and data.strip():
            self.heading.append(data.strip())


def fetch_provider_profile_html(provider_id: str) -> tuple[str, str | None]:
    url = f"https://huggingface.co/{provider_id}"
    try:
        response = requests.get(url, headers={"Accept": "text/html"}, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        LOGGER.debug("HTML metadata request failed %s: %s", url, exc)
        return provider_id, None
    if not response.ok:
        LOGGER.debug("HTML metadata request %s returned %s", url, response.status_code)
        return provider_id, None

    parser = _ProfileHTMLParser()
    parser.feed(response.text)

    display_name = parser.meta.get("og:title") or (" ".join(parser.heading).strip() if parser.heading else provider_id)
    raw_avatar = next(iter(parser.img_candidates), None) or parser.meta.get("og:image")
    avatar_url = urljoin(url, raw_avatar) if raw_avatar else None
    return display_name or provider_id, avatar_url


def save_models(conn: psycopg.Connection, provider: str, records: Iterable[ModelRecord], *, started_at: datetime) -> tuple[int, int]:
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
                    is_open_source, price, opencompass_rank, huggingface_rank
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_id) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    model_name = EXCLUDED.model_name,
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags,
                    created_at = EXCLUDED.created_at,
                    downloads = EXCLUDED.downloads,
                    likes = EXCLUDED.likes,
                    model_card_url = EXCLUDED.model_card_url,
                    inserted_at = EXCLUDED.inserted_at,
                    is_open_source = EXCLUDED.is_open_source,
                    price = COALESCE(EXCLUDED.price, models.price),
                    opencompass_rank = COALESCE(EXCLUDED.opencompass_rank, models.opencompass_rank),
                    huggingface_rank = COALESCE(EXCLUDED.huggingface_rank, models.huggingface_rank)
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
                    record.is_open_source,
                    json.dumps(record.price, ensure_ascii=False) if record.price is not None else None,
                    record.opencompass_rank,
                    record.huggingface_rank,
                ),
            )
            inserted_row = cursor.rowcount
            cursor.execute("DELETE FROM model_tags WHERE model_id = %s", (record.model_id,))
            if record.tags:
                tag_rows = [
                    (record.model_id, tag, record.inserted_at)
                    for tag in record.tags
                ]
                cursor.executemany(
                    """
                    INSERT INTO model_tags (model_id, tag, inserted_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (model_id, tag) DO UPDATE SET inserted_at = EXCLUDED.inserted_at
                    """,
                    tag_rows,
                )
            if inserted_row:
                inserted += 1
        finished_at = datetime.now(timezone.utc)
        cursor.execute(
            """
            INSERT INTO sync_log (provider, started_at, finished_at, status, processed, inserted, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
    token = os.getenv("HF_TOKEN")
    with ensure_db() as conn:
        for provider in providers:
            LOGGER.info("Fetching models for provider %s", provider)
            display_name, avatar_url = resolve_provider_profile(client, provider)
            avatar_content, avatar_mime = download_provider_avatar(avatar_url, token)
            try:
                upsert_provider(conn, provider, avatar_url, display_name, avatar_content, avatar_mime)
            except Exception as exc:  # pragma: no cover - database failure
                LOGGER.warning("Failed to upsert provider %s metadata: %s", provider, exc)
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
