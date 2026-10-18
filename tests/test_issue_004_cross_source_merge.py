"""ISSUE-004 收尾：同一模型在 HF 与 OpenRouter 各有行时，时间轴上只显示一张卡。

`models.merged_into` 把 OR 行挂到 HF 行后面（OU 行是"被合并行"），这里锁住四条行为：

  ① 列表（`/api/models` 与 `/api/timeline`）不显示被合并行，但**保留**指向已删除目标的
    悬挂行（宁可多一张卡，也不要让模型凭空消失）；
  ② 合并目标那张卡要带上 OR 行的价格（价格通常只存在于 OR 行）；
  ③ 详情接口收到被合并行的 id 时解析到合并目标，不 404；
  ④ 榜单分挂在被合并行上时，合并目标的 `arena_score` 也要能看到。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg
import pytest

HF_ID = "acme/merge-hf"
OR_ID = "acme/merge-or"
ORPHAN_ID = "acme/merge-orphan"

HF_PRICE = None
OR_PRICE = {"prompt": "0.0000005", "completion": "0.0000015"}


def _insert(conn: psycopg.Connection, *, model_id: str, merged_into: str | None, price, provider="acme"):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM models WHERE model_id = %s", (model_id,))
        cur.execute(
            """
            INSERT INTO models
                (model_id, provider, model_name, description, tags, created_at,
                 downloads, likes, model_card_url, inserted_at, is_open_source,
                 price, huggingface_rank, source, merged_into)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                model_id,
                provider,
                f"Name of {model_id}",
                "desc",
                '["llm"]',
                datetime(2025, 5, 1, tzinfo=timezone.utc),
                1,
                1,
                "https://example.com/card",
                datetime(2025, 5, 1, tzinfo=timezone.utc),
                True,
                json.dumps(price) if price is not None else None,
                None,
                "huggingface" if merged_into is None else "openrouter",
                merged_into,
            ),
        )
    conn.commit()


@pytest.fixture()
def merged_pair(ensure_seeded: str):
    with psycopg.connect(ensure_seeded) as conn:
        _insert(conn, model_id=HF_ID, merged_into=None, price=HF_PRICE)
        _insert(conn, model_id=OR_ID, merged_into=HF_ID, price=OR_PRICE)
        _insert(conn, model_id=ORPHAN_ID, merged_into="acme/does-not-exist", price=None)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_arena_info WHERE model_id IN (%s, %s)", (HF_ID, OR_ID))
            cur.execute(
                """
                INSERT INTO model_arena_info (model_id, source, rank, score, category)
                VALUES (%s, 'lmarena', 7, 1400.5, 'overall')
                """,
                (OR_ID,),
            )
        conn.commit()
    yield ensure_seeded
    with psycopg.connect(ensure_seeded) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM model_arena_info WHERE model_id IN (%s, %s)", (HF_ID, OR_ID))
        cur.execute("DELETE FROM models WHERE model_id IN (%s, %s, %s)", (HF_ID, OR_ID, ORPHAN_ID))
        conn.commit()


def _ids(payload: dict) -> list[str]:
    return [item["model_id"] for item in payload["items"]]


def test_models_list_hides_merged_rows_but_keeps_orphans(client, merged_pair):
    response = client.get("/api/models", params={"page_size": 100})
    assert response.status_code == 200
    ids = _ids(response.json())
    assert OR_ID not in ids, "被合并的 OR 行不该单独出现在列表里"
    assert HF_ID in ids, "合并目标必须仍然可见"
    assert ORPHAN_ID in ids, "指向已删除目标的悬挂行必须保留，否则模型会凭空消失"


def test_timeline_hides_merged_row_and_borrows_price(client, merged_pair):
    response = client.get("/api/timeline", params={"preset": "all", "page_size": 500})
    assert response.status_code == 200
    payload = response.json()
    ids = _ids(payload)
    assert OR_ID not in ids
    assert HF_ID in ids

    hf_item = next(item for item in payload["items"] if item["model_id"] == HF_ID)
    assert hf_item["price"] == OR_PRICE, "合并目标要带上 OR 行的价格"
    assert payload["total"] == len(payload["items"]) or payload["total"] >= len(payload["items"])


def test_detail_resolves_merged_id_to_canonical(client, merged_pair):
    for requested in (HF_ID, OR_ID):
        response = client.post(
            "/api/models/analysis-with-scores", json={"model_id": requested}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["model_id"] == HF_ID, f"请求 {requested} 应当落到合并目标上"
        assert body["price"] == OR_PRICE


def test_arena_scores_on_merged_row_are_visible_on_canonical(client, merged_pair):
    response = client.post("/api/models/analysis-with-scores", json={"model_id": HF_ID})
    assert response.status_code == 200
    arena = response.json()["arena_score"]
    assert arena is not None
    assert arena["has_score"] is True
    assert arena["details"], "挂在被合并行上的榜单分必须出现在合并目标上"
    assert arena["details"][0]["model_id"] == OR_ID
