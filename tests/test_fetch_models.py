import os
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest

from src.scraper import fetch_models as fm

TEST_DB_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DB_URL:
    pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL-dependent tests.", allow_module_level=True)


def _make_model(model_id: str, *, created_at: datetime | None = None, tags=None, description: str = ""):
    created_at = created_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        modelId=model_id,
        cardData={"summary": description} if description else {},
        description=description,
        tags=tags or ["text-generation"],
        created_at=created_at,
        lastModified=created_at,
        downloads=123,
        likes=45,
    )


def _reset_database() -> None:
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE sync_log, models RESTART IDENTITY")
        conn.commit()


def test_fetch_and_store_inserts(monkeypatch):
    monkeypatch.setenv("PROVIDERS", "meta-llama")
    monkeypatch.setenv("HF_TOKEN", "dummy")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)

    models = [
        _make_model("meta-llama/Llama-1", description="Model one"),
        _make_model("meta-llama/Llama-2", description="Model two"),
        _make_model("meta-llama/Llama-1", description="Duplicate"),
    ]

    class FakeClient:
        def list_models(self, **kwargs):
            return models

    monkeypatch.setattr(fm, "hf_client", lambda: FakeClient())

    fm.create_schema(TEST_DB_URL)
    _reset_database()

    results = fm.fetch_and_store(limit=10)

    assert results == {"meta-llama": (3, 2)}

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT model_id, description FROM models ORDER BY model_id")
            rows = cursor.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "meta-llama/Llama-1"
            assert "Model one" in rows[0][1]

            cursor.execute("SELECT processed, inserted FROM sync_log")
            sync_rows = cursor.fetchall()
            assert sync_rows == [(3, 2)]


@pytest.mark.parametrize("raw, expected", [
    ("meta-llama, google ", ["meta-llama", "google"]),
    ("", []),
    (None, []),
])
def test_get_providers(raw, expected):
    assert fm.get_providers(raw) == expected

