import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.scraper import fetch_models as fm


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


def test_fetch_and_store_inserts(monkeypatch, tmp_path):
    db_path = tmp_path / "silicon_river.db"
    monkeypatch.setenv("PROVIDERS", "meta-llama")
    monkeypatch.setenv("HF_TOKEN", "dummy")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    models = [
        _make_model("meta-llama/Llama-1", description="Model one"),
        _make_model("meta-llama/Llama-2", description="Model two"),
        _make_model("meta-llama/Llama-1", description="Duplicate"),
    ]

    class FakeClient:
        def list_models(self, **kwargs):
            return models

    monkeypatch.setattr(fm, "hf_client", lambda: FakeClient())

    results = fm.fetch_and_store(limit=10)

    assert results == {"meta-llama": (3, 2)}

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT model_id, description FROM models ORDER BY model_id").fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "meta-llama/Llama-1"
        assert "Model one" in rows[0][1]

        sync_rows = conn.execute("SELECT processed, inserted FROM sync_log").fetchall()
        assert sync_rows == [(3, 2)]


@pytest.mark.parametrize("raw, expected", [
    ("meta-llama, google ", ["meta-llama", "google"]),
    ("", []),
    (None, []),
])
def test_get_providers(raw, expected):
    assert fm.get_providers(raw) == expected
