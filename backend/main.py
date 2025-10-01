"""FastAPI application exposing Silicon River data."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://USER:PASSWORD@HOST:5432/silicon_river")


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

