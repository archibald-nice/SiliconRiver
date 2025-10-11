"""FastAPI application exposing Silicon River data."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import psycopg
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from psycopg.rows import dict_row
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river")
AVATAR_FETCH_TIMEOUT = float(os.getenv("AVATAR_FETCH_TIMEOUT", "6"))
AVATAR_CACHE_TTL = int(os.getenv("AVATAR_CACHE_TTL", "86400"))
AVATAR_MAX_BYTES = int(os.getenv("AVATAR_MAX_BYTES", "524288"))


def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(DATABASE_URL)
    return conn


class Model(BaseModel):
    model_id: str
    provider: str
    model_name: str
    description: Optional[str]
    tags: List[str]
    created_at: str
    downloads: Optional[int]
    likes: Optional[int]
    model_card_url: str


class ModelList(BaseModel):
    items: List[Model]
    total: int
    page: int
    page_size: int


class ProviderStat(BaseModel):
    provider: str
    model_count: int


class TimelineModel(BaseModel):
    model_id: str
    provider: str
    model_name: str
    description: Optional[str]
    created_at: str
    model_card_url: str
    tags: List[str]
    avatar_url: Optional[str] = None


class TimelineResponse(BaseModel):
    items: List[TimelineModel]
    total: int
    page: int
    page_size: int
    start: str
    end: str
    preset: str
    label: str


app = FastAPI(title="Silicon River API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@app.get("/api/models", response_model=ModelList)
async def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    provider: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    conn: psycopg.Connection = Depends(get_db),
):
    offset = (page - 1) * page_size
    filters: List[str] = []
    params: List[object] = []

    if provider:
        filters.append("provider = %s")
        params.append(provider)
    if tag:
        filters.append("tags ILIKE %s")
        params.append(f"%{tag}%")
    if search:
        filters.append("(model_name ILIKE %s OR description ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"SELECT COUNT(*) AS total FROM models{where_clause}", params)
        total_row = cursor.fetchone()
        total = int(total_row["total"]) if total_row else 0

        cursor.execute(
            f"""
            SELECT model_id, provider, model_name, description, tags, created_at, downloads, likes, model_card_url
            FROM models
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            [*params, page_size, offset],
        )
        rows = cursor.fetchall()

    items = [
        Model(
            model_id=row["model_id"],
            provider=row["provider"],
            model_name=row["model_name"],
            description=row["description"],
            tags=_parse_tags(row["tags"]),
            created_at=row["created_at"],
            downloads=row["downloads"],
            likes=row["likes"],
            model_card_url=row["model_card_url"],
        )
        for row in rows
    ]

    return ModelList(items=items, total=total, page=page, page_size=page_size)


@app.get("/api/models/{model_id}", response_model=Model)
async def get_model(model_id: str, conn: psycopg.Connection = Depends(get_db)):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT model_id, provider, model_name, description, tags, created_at, downloads, likes, model_card_url
            FROM models
            WHERE model_id = %s
            """,
            [model_id],
        )
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    return Model(
        model_id=row["model_id"],
        provider=row["provider"],
        model_name=row["model_name"],
        description=row["description"],
        tags=_parse_tags(row["tags"]),
        created_at=row["created_at"],
        downloads=row["downloads"],
        likes=row["likes"],
        model_card_url=row["model_card_url"],
    )


@app.get("/api/timeline", response_model=TimelineResponse)
async def timeline_models(
    preset: str = Query("30d", regex="^(30d|6m|1y)"),
    year: Optional[int] = Query(None, ge=1900, le=3000),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=10, le=500),
    sort: str = Query("asc", regex="^(asc|desc)"),
    provider: Optional[str] = Query(None),
    model_name: Optional[str] = Query(None),
    conn: psycopg.Connection = Depends(get_db),
):
    start_dt, end_dt, label = _calculate_timeline_window(preset=preset, year=year)
    start = start_dt.isoformat()
    end = end_dt.isoformat()
    order_clause = "ASC" if sort == "asc" else "DESC"
    offset = (page - 1) * page_size
    filters: List[str] = ["m.created_at BETWEEN %s AND %s"]
    params: List[object] = [start, end]

    if provider:
        filters.append("m.provider = %s")
        params.append(provider)
    if model_name:
        filters.append("m.model_name ILIKE %s")
        params.append(f"%{model_name}%")

    where_clause = " AND ".join(filters)

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM models AS m
            WHERE {where_clause}
            """,
            params,
        )
        total_row = cursor.fetchone()
        total = int(total_row["total"]) if total_row else 0

        query_params = [*params, page_size, offset]
        cursor.execute(
            f"""
            SELECT
                m.model_id,
                m.provider,
                m.model_name,
                m.description,
                m.tags,
                m.created_at,
                m.model_card_url,
                p.avatar_url
            FROM models AS m
            LEFT JOIN providers AS p ON m.provider = p.provider_id
            WHERE {where_clause}
            ORDER BY m.created_at {order_clause}
            LIMIT %s OFFSET %s
            """,
            query_params,
        )
        rows = cursor.fetchall()

    items = [
        TimelineModel(
            model_id=row["model_id"],
            provider=row["provider"],
            model_name=row["model_name"],
            description=row["description"],
            created_at=row["created_at"],
            model_card_url=row["model_card_url"],
            tags=_parse_tags(row["tags"]),
            avatar_url=row.get("avatar_url"),
        )
        for row in rows
    ]

    return TimelineResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        start=start,
        end=end,
        preset="year" if year is not None else preset,
        label=label,
    )


@app.get("/api/stats/providers", response_model=List[ProviderStat])
async def provider_stats(conn: psycopg.Connection = Depends(get_db)):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT provider, COUNT(*) as model_count
            FROM models
            GROUP BY provider
            ORDER BY model_count DESC
            """
        )
        rows = cursor.fetchall()
    return [ProviderStat(provider=row["provider"], model_count=row["model_count"]) for row in rows]


@app.get("/api/providers/{provider_id}/avatar")
async def provider_avatar(provider_id: str, conn: psycopg.Connection = Depends(get_db)):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT avatar_blob, avatar_mime, avatar_url FROM providers WHERE provider_id = %s",
            (provider_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")

    avatar_blob = row.get("avatar_blob")
    avatar_mime = row.get("avatar_mime") or "image/png"
    if avatar_blob:
        headers = {"Cache-Control": f"public, max-age={AVATAR_CACHE_TTL}"}
        return Response(content=avatar_blob, media_type=avatar_mime, headers=headers)

    avatar_url = row.get("avatar_url")
    if not avatar_url:
        raise HTTPException(status_code=404, detail="Avatar unavailable")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(AVATAR_FETCH_TIMEOUT, connect=AVATAR_FETCH_TIMEOUT),
            follow_redirects=True,
            headers={"Accept": "image/*,application/octet-stream;q=0.9"},
        ) as client:
            upstream = await client.get(avatar_url)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch avatar: {exc}") from exc

    if upstream.status_code == 404:
        raise HTTPException(status_code=404, detail="Avatar not found")
    if upstream.status_code >= 500:
        raise HTTPException(status_code=502, detail="Avatar provider error")
    if upstream.status_code >= 400:
        raise HTTPException(status_code=upstream.status_code, detail="Avatar fetch error")

    content = upstream.content
    if len(content) <= AVATAR_MAX_BYTES:
        content_type = upstream.headers.get("content-type", "image/png")
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE providers
                    SET avatar_blob = %s, avatar_mime = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE provider_id = %s
                    """,
                    (content, content_type, provider_id),
                )
            conn.commit()
        except Exception:  # pragma: no cover - cache write failure
            conn.rollback()
    else:
        content_type = upstream.headers.get("content-type", "image/png")

    headers = {"Cache-Control": f"public, max-age={AVATAR_CACHE_TTL}"}
    for header in ("ETag", "Last-Modified"):
        value = upstream.headers.get(header)
        if value:
            headers[header] = value

    return Response(content=content, media_type=content_type, headers=headers)


def _calculate_timeline_window(preset: str, year: Optional[int]) -> tuple[datetime, datetime, str]:
    now = datetime.utcnow()
    if year is not None:
        start_dt = datetime(year, 1, 1)
        end_dt = datetime(year, 12, 31, 23, 59, 59)
        return start_dt, end_dt, f"{year}年"

    preset = preset or "30d"
    if preset == "6m":
        start_dt = now - timedelta(days=182)
        label = "近半年"
    elif preset == "1y":
        start_dt = datetime(now.year, 1, 1)
        end_dt = now
        return start_dt, end_dt, "今年"
    else:
        start_dt = now - timedelta(days=30)
        label = "近30天"
    end_dt = now
    return start_dt, end_dt, label

def _parse_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


@app.get("/health")
async def healthcheck():
    return {"status": "ok"}




