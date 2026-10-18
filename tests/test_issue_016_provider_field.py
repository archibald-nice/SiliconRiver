"""ISSUE-016 回归：`/api/models/analysis` 必须返回 `provider`，且取自 `models.provider`。

现场表现：前端拿 `model_id.split("/")[0]` 当厂商名，于是 `aion-labs/aion-3.0` 显示成
`aion-labs`（仓库组织名），而站内筛选用的是库里的 `aionlabs`；头像也因厂商名不对而 404。

这里的用例刻意让 `model_analysis.provider`（分析时抄下的副本）与 `models.provider`
**不一致**：只有真的从 `models` 表取，才可能返回 `aionlabs`；从 `model_id` 前缀或
`model_analysis.provider` 取都会得到 `aion-labs`，用例会立刻失败。
"""
from __future__ import annotations

import pytest

# 前缀（仓库组织名）/ model_analysis 里的副本 / models 里的权威 provider，三者互不相同
MODEL_ID = "aion-labs/aion-3.0"
PREFIX = "aion-labs"
STALE_COPY = "aion-labs"
AUTHORITATIVE = "aionlabs"


@pytest.fixture()
def aion_model(ensure_seeded):
    """临时插入一个「前缀 ≠ provider」的模型及其分析行，结束后彻底删掉。

    测试库的样本数据是 session 级共享的（其它用例断言 models 表只有 3 行），
    所以这里必须自己收尾，不能污染 `ensure_seeded` 的样本数据。
    """
    import psycopg

    with psycopg.connect(ensure_seeded, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO models
                (model_id, provider, model_name, description, tags, created_at,
                 downloads, likes, model_card_url, inserted_at, is_open_source,
                 price, huggingface_rank)
            VALUES (%s, %s, 'Aion 3.0', 'provider differs from model_id prefix', '["llm"]',
                    '2024-09-01 00:00:00', 1, 2, 'https://example.com/aion',
                    '2024-09-01 00:00:00', TRUE, NULL, NULL)
            """,
            (MODEL_ID, AUTHORITATIVE),
        )
        cur.execute(
            """
            INSERT INTO model_analysis
                (model_id, provider, model_name, analysis_summary, key_features,
                 use_cases, llm_model_used, is_milestone, milestone_features)
            VALUES (%s, %s, 'Aion 3.0', 'aion summary', ARRAY['fast'], ARRAY['chat'],
                    'deepseek-chat', FALSE, NULL)
            """,
            (MODEL_ID, STALE_COPY),
        )
        # tags 走 model_tags 表（不是 models.tags 那个 JSON 文本列）
        cur.execute(
            "INSERT INTO model_tags (model_id, tag) VALUES (%s, %s)",
            (MODEL_ID, "llm"),
        )
    try:
        yield MODEL_ID
    finally:
        with psycopg.connect(ensure_seeded, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM model_tags WHERE model_id = %s", (MODEL_ID,))
            cur.execute("DELETE FROM model_analysis WHERE model_id = %s", (MODEL_ID,))
            cur.execute("DELETE FROM models WHERE model_id = %s", (MODEL_ID,))


def test_analysis_response_provider_comes_from_models_table(client, aion_model):
    response = client.post("/api/models/analysis", json={"model_id": aion_model})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider"] == AUTHORITATIVE
    # 反证：这两个推导方式都只会得到 PREFIX
    assert body["provider"] != PREFIX
    assert body["provider"] != body["model_id"].split("/")[0]


def test_analysis_response_keeps_existing_fields(client, aion_model):
    """补字段不能动老字段：前端其它地方仍在读这些键。"""
    body = client.post("/api/models/analysis", json={"model_id": aion_model}).json()
    assert {
        "model_id",
        "provider",
        "analysis_summary",
        "key_features",
        "use_cases",
        "performance_metrics",
        "llm_model_used",
        "analyzed_at",
        "tags",
        "is_milestone",
        "milestone_features",
        "updated_at",
    } <= set(body)
    assert body["model_id"] == MODEL_ID
    assert body["analysis_summary"] == "aion summary"
    assert body["key_features"] == ["fast"]
    assert body["use_cases"] == ["chat"]
    assert body["llm_model_used"] == "deepseek-chat"
    assert body["is_milestone"] is False
    assert body["tags"] == ["llm"]


def test_seeded_analysis_still_returns_provider_and_old_fields(client):
    """样本数据这条路径（provider 两边相同）也要保持不变。"""
    body = client.post("/api/models/analysis", json={"model_id": "acme/alpha-1"}).json()
    assert body["provider"] == "acme"
    assert body["key_features"] == ["fast"]
    assert body["is_milestone"] is True
    assert body["milestone_features"] == "first"
    assert body["tags"] == ["llm"]


def test_analysis_404_detail_is_unchanged(client):
    """没有分析行时的错误语义不能被顺手改掉。"""
    response = client.post("/api/models/analysis", json={"model_id": "acme/beta-2"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Model analysis not found"


def test_analyzed_list_endpoint_still_works(client):
    """/api/models/analyzed 复用了同一个 ModelAnalysis 模型，补字段后不能坏。"""
    response = client.get("/api/models/analyzed", params={"page_size": 50})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["model_id"] == "acme/alpha-1"
    assert body["items"][0]["tags"] == ["llm"]
