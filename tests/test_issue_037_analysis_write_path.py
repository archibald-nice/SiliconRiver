"""ISSUE-037：分析结果写库要复用连接、批量写标签。

2026-10-19 的观测报告指出：分析环节 LLM 侧正常（0.6–0.7 秒/次），但整轮只有
约 5 秒/模型 —— 因为 `AnalysisIntegration._save_analysis_to_db` 每个模型都
`psycopg.connect()` 新建一条跨洋连接（TCP + TLS + pooler 认证），再加上
「每个标签一条 INSERT」，14 个标签就是 14 次往返。

这组用例用**真数据库**（`db_url`）验证三件事：
  ① 一串模型共用**一条**连接（不是每模型一条）；
  ② 标签用 `executemany` 一次写完，而不是逐条 execute；
  ③ 连接坏掉时能丢掉重建，不会让后续模型连带失败。
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest

from src.analysis import integration as mod
from src.analysis.async_analyzer import AnalysisResult

MODEL_IDS = ["acme/issue-037-a", "acme/issue-037-b", "acme/issue-037-c"]


def _result(model_id: str) -> AnalysisResult:
    return AnalysisResult(
        model_id=model_id,
        analysis_summary=f"summary of {model_id}",
        key_features=["feature"],
        use_cases=["use-case"],
        performance_metrics={"latency": 1.0},
        llm_model_used="deepseek-chat",
    )


def _clean(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_tags WHERE model_id = ANY(%s)", (MODEL_IDS,))
            cur.execute("DELETE FROM model_analysis WHERE model_id = ANY(%s)", (MODEL_IDS,))
            cur.execute("DELETE FROM models WHERE model_id = ANY(%s)", (MODEL_IDS,))
        conn.commit()


def _seed_models(db_url: str) -> None:
    """model_tags 有外键指向 models，先把这三个模型行建出来。"""
    now = datetime.now(timezone.utc)
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for index, model_id in enumerate(MODEL_IDS):
                cur.execute(
                    """
                    INSERT INTO models (model_id, provider, model_name, description, tags,
                                        created_at, model_card_url, inserted_at)
                    VALUES (%s, 'acme', %s, '', '[]', %s, 'https://example.test/m', %s)
                    ON CONFLICT (model_id) DO NOTHING
                    """,
                    (model_id, f"Model {index}", now, now),
                )
        conn.commit()


@pytest.fixture()
def clean(db_url: str):
    _clean(db_url)
    _seed_models(db_url)
    yield db_url
    _clean(db_url)


def test_one_connection_for_many_models(clean: str, monkeypatch):
    calls = {"connect": 0}
    real_connect = psycopg.connect

    def counting_connect(*args, **kwargs):
        calls["connect"] += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", counting_connect)

    integration = mod.AnalysisIntegration(db_url=clean)
    for index, model_id in enumerate(MODEL_IDS):
        saved = integration._save_analysis_to_db(
            model_id=model_id,
            model_name=f"Model {index}",
            provider="acme",
            analysis_result=_result(model_id),
            generated_tags=["llm", "chat"],
        )
        assert saved is True
    integration.close()

    assert calls["connect"] == 1, "三个模型应当共用一条连接，而不是每个模型新建一条"

    with psycopg.connect(clean) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM model_analysis WHERE model_id = ANY(%s)", (MODEL_IDS,))
        assert cur.fetchone()[0] == len(MODEL_IDS)
        cur.execute("SELECT count(*) FROM model_tags WHERE model_id = ANY(%s)", (MODEL_IDS,))
        assert cur.fetchone()[0] == len(MODEL_IDS) * 2


def test_tags_written_with_executemany(clean: str, monkeypatch):
    counts = {"execute": 0, "executemany": 0}

    class CountingCursor(psycopg.Cursor):
        def execute(self, *args, **kwargs):
            counts["execute"] += 1
            return super().execute(*args, **kwargs)

        def executemany(self, *args, **kwargs):
            counts["executemany"] += 1
            return super().executemany(*args, **kwargs)

    real_connect = psycopg.connect

    def connect_with_counting_cursor(*args, **kwargs):
        kwargs.setdefault("cursor_factory", CountingCursor)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(mod.psycopg, "connect", connect_with_counting_cursor)

    integration = mod.AnalysisIntegration(db_url=clean)
    integration._save_analysis_to_db(
        model_id=MODEL_IDS[0],
        model_name="Model 0",
        provider="acme",
        analysis_result=_result(MODEL_IDS[0]),
        generated_tags=["llm", "chat", "reasoning", "code"],
    )
    integration.close()

    # 逐条 INSERT 时 executemany 会是 0、execute 会是 4 次以上
    assert counts["executemany"] == 1, f"四个标签应当一次 executemany 写完，实际 {counts}"
    assert counts["execute"] == 2, f"标签之外只应有 upsert + DELETE，实际 {counts}"


def test_dropped_connection_is_recreated(clean: str):
    integration = mod.AnalysisIntegration(db_url=clean)
    integration._save_analysis_to_db(
        model_id=MODEL_IDS[1],
        model_name="Model 1",
        provider="acme",
        analysis_result=_result(MODEL_IDS[1]),
        generated_tags=["llm"],
    )
    first = integration._get_connection()

    # 模拟「Supabase 把空闲连接踢掉」
    integration._conn.close()
    integration._drop_connection()
    assert integration._conn is None

    second = integration._get_connection()
    assert second is not first
    assert second.closed is False
    integration.close()
    assert integration._conn is None
