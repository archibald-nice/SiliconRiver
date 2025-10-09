import os
from datetime import datetime, timezone
from types import SimpleNamespace

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None  # type: ignore
try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover
    TestClient = None  # type: ignore
import importlib
import pytest

try:
    from src.scraper import fetch_models as fm
except ModuleNotFoundError:  # pragma: no cover
    pytest.skip("src.scraper is unavailable in this environment", allow_module_level=True)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DB_URL or psycopg is None or TestClient is None:
    pytest.skip("PostgreSQL tests require psycopg, fastapi[testclient], and TEST_DATABASE_URL", allow_module_level=True)


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

    backend_main = importlib.import_module("backend.main")
    importlib.reload(backend_main)
    client = TestClient(backend_main.app)
    response = client.get("/api/timeline", params={"preset": "1y", "page_size": 5, "sort": "asc"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    assert payload["total"] >= len(payload["items"])
    assert payload["page"] == 1
    assert payload["page_size"] == 5
    assert payload["start"] <= payload["end"]

    provider_response = client.get(
        "/api/timeline",
        params={"preset": "1y", "page_size": 5, "sort": "asc", "provider": "meta-llama"},
    )
    assert provider_response.status_code == 200
    provider_payload = provider_response.json()
    assert provider_payload["items"]
    assert all(item["provider"] == "meta-llama" for item in provider_payload["items"])

    search_response = client.get(
        "/api/timeline",
        params={"preset": "1y", "page_size": 5, "sort": "asc", "model_name": "Llama-2"},
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["items"]
    assert all("llama-2" in item["model_name"].lower() for item in search_payload["items"])


@pytest.mark.parametrize("raw, expected", [
    ("meta-llama, google ", ["meta-llama", "google"]),
    ("", []),
    (None, []),
])
def test_get_providers(raw, expected):
    assert fm.get_providers(raw) == expected

