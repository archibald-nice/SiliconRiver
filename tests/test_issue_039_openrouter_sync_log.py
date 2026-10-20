"""ISSUE-039：OpenRouter 侧也要写 `sync_log` 审计行。

问题：`sync_log` 只有 Hugging Face 侧的记录（provider 一列全是 HF 的 org 名），
OpenRouter 那条线挂了、数据悄悄停更，只能靠「最近怎么没有新模型了」察觉——
而那可能是一两周后的事。

这组用例锁两件事：
  ① `write_sync_log()` 真能把一行写进表里（字段语义与 HF 侧一致）；
  ② `fetch_and_store()` 每写完一个 provider 就落一行审计（而不是整轮一行或零行）。
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone

import psycopg

from src.scraper import fetch_models_openrouter as om


def test_write_sync_log_inserts_row(db_url: str):
    provider = "issue039-probe"
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sync_log WHERE provider = %s", (provider,))
        conn.commit()

        started = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
        om.write_sync_log(conn, provider, started, processed=12, inserted=3)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, processed, inserted, finished_at FROM sync_log WHERE provider = %s",
                (provider,),
            )
            rows = cur.fetchall()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sync_log WHERE provider = %s", (provider,))
        conn.commit()

    assert len(rows) == 1
    status, processed, inserted, finished_at = rows[0]
    assert (status, processed, inserted) == ("success", 12, 3)
    assert finished_at is not None


class _FakeStore:
    def __init__(self) -> None:
        self.audit: list[tuple[str, int, int]] = []

    def upsert_provider(self, conn, provider_id, display_name=None, avatar_url=None) -> None:
        pass

    def save_models(self, conn, provider, records) -> tuple[int, int]:
        records = list(records)
        return len(records), 0

    def write_sync_log(self, conn, provider, started_at, processed, inserted) -> None:
        self.audit.append((provider, processed, inserted))


def test_fetch_and_store_writes_one_audit_row_per_provider(monkeypatch):
    monkeypatch.setenv("PROVIDERS_OPENROUTER", "acme,globex")
    payload = [
        {"id": "acme/alpha-1", "name": "Acme: Alpha 1", "created": 1_760_000_000},
        {"id": "acme/alpha-2", "name": "Acme: Alpha 2", "created": 1_760_000_000},
        {"id": "globex/beta-1", "name": "Globex: Beta 1", "created": 1_760_000_000},
    ]
    fake = _FakeStore()
    monkeypatch.setattr(om, "fetch_remote_models", lambda endpoint: payload)
    monkeypatch.setattr(om, "ensure_db", lambda *a, **k: contextlib.nullcontext(object()))
    monkeypatch.setattr(om, "upsert_provider", fake.upsert_provider)
    monkeypatch.setattr(om, "save_models", fake.save_models)
    monkeypatch.setattr(om, "write_sync_log", fake.write_sync_log)

    summary = om.fetch_and_store()

    assert summary == {"acme": (2, 0), "globex": (1, 0)}
    assert sorted(fake.audit) == [("acme", 2, 0), ("globex", 1, 0)], (
        "每个 provider 都应当有一行独立的审计记录"
    )
