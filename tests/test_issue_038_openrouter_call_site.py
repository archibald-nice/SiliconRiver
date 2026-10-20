"""ISSUE-038：OpenRouter 侧写库要「每家一次」，而不是「每个模型一次」。

2026-10-20 夜跑实测：同步总共 9 分 57 秒，其中 HF 2 分 27 秒、**OR 7 分 30 秒**。
HF 侧批量写已经生效（write 段 1–2 秒/家），OR 侧虽然 SQL 换成批量的，但调用点仍是
`for item in selected_models: save_models(conn, provider, [record])`——
每批只有 1 条记录，等于没批量化，而且每个模型还多一次 upsert_provider。

这组用例锁住两件事：
  ① 同一个 provider 的多条记录只调用一次 `save_models`；
  ② provider 的展示名只 upsert 一次，且取该家第一条记录里的展示名。
"""

from __future__ import annotations

import pytest

from src.scraper import fetch_models_openrouter as om

PAYLOAD = [
    {"id": "acme/alpha", "name": "Acme: Alpha", "created": 1_760_000_000,
     "pricing": {"prompt": "0.0000001"}},
    {"id": "acme/beta", "name": "Acme: Beta", "created": 1_760_000_100,
     "pricing": {"prompt": "0.0000002"}},
    {"id": "acme/gamma", "name": "Acme: Gamma", "created": 1_760_000_200},
    {"id": "globex/delta", "name": "Globex: Delta", "created": 1_760_000_300},
]


class _FakeConn:
    """只为让 fetch_and_store 的 with 语句跑通，不碰真库。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_records_are_grouped_by_provider(monkeypatch):
    calls: list[tuple[str, int]] = []
    provider_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(om, "load_config", lambda: None)
    monkeypatch.setattr(om, "fetch_remote_models", lambda endpoint: list(PAYLOAD))
    monkeypatch.setattr(om, "get_providers", lambda raw: ["acme", "globex"])
    monkeypatch.setattr(om, "ensure_db", lambda: _FakeConn())

    def fake_save(conn, provider, records):
        records = list(records)
        calls.append((provider, len(records)))
        return len(records), 0

    monkeypatch.setattr(om, "save_models", fake_save)
    monkeypatch.setattr(
        om,
        "upsert_provider",
        lambda conn, provider_id, display_name=None, avatar_url=None: provider_calls.append(
            (provider_id, display_name)
        ),
    )

    results = om.fetch_and_store()

    assert sorted(calls) == [("acme", 3), ("globex", 1)], f"应按 provider 聚合后再写：{calls}"
    assert provider_calls == [("acme", "Acme"), ("globex", "Globex")]
    assert results["acme"] == (3, 0)
    assert results["globex"] == (1, 0)


def test_provider_upsert_happens_once_per_provider(monkeypatch):
    counter = {"save": 0, "provider": 0}

    monkeypatch.setattr(om, "load_config", lambda: None)
    monkeypatch.setattr(om, "fetch_remote_models", lambda endpoint: list(PAYLOAD))
    monkeypatch.setattr(om, "get_providers", lambda raw: ["acme", "globex"])
    monkeypatch.setattr(om, "ensure_db", lambda: _FakeConn())
    monkeypatch.setattr(
        om, "save_models", lambda conn, provider, records: (len(list(records)), 0)
    )

    def count_provider(*args, **kwargs):
        counter["provider"] += 1

    monkeypatch.setattr(om, "upsert_provider", count_provider)
    om.fetch_and_store()

    assert counter["provider"] == 2, "每家只 upsert 一次 provider，不是每个模型一次"
