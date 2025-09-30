"""FastAPI application exposing Silicon River data."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR.parent / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/silicon_river.db")


def _extract_sqlite_path(url: str) -> Path:
    if url.startswith("sqlite:///"):
        relative_path = url.replace("sqlite:///", "")
        return (BASE_DIR.parent / relative_path).resolve()
    raise ValueError("Only sqlite:/// paths are supported by the default backend service.")


def get_connection() -> sqlite3.Connection:
    db_path = _extract_sqlite_path(DATABASE_URL)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
    conn: sqlite3.Connection = Depends(get_db),
):
    offset = (page - 1) * page_size
    filters = []
    params: List[object] = []

    if provider:
        filters.append("provider = ?")
        params.append(provider)
    if tag:
        filters.append("tags LIKE ?")
        params.append(f"%{tag}%")
    if search:
        filters.append("(model_name LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    total = conn.execute(f"SELECT COUNT(*) FROM models {where_clause}", params).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT model_id, provider, model_name, description, tags, created_at, downloads, likes, model_card_url
        FROM models
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()

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
async def get_model(model_id: str, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(
        """
        SELECT model_id, provider, model_name, description, tags, created_at, downloads, likes, model_card_url
        FROM models
        WHERE model_id = ?
        """,
        [model_id],
    ).fetchone()
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
async def provider_stats(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """
        SELECT provider, COUNT(*) as model_count
        FROM models
        GROUP BY provider
        ORDER BY model_count DESC
        """
    ).fetchall()
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
