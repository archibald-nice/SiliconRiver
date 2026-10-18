"""ISSUE-035：`inserted_at` 是「首次入库时间」，不能被 upsert 里的更新覆盖。

历史行为：`ON CONFLICT (model_id) DO UPDATE SET ... inserted_at = EXCLUDED.inserted_at`
让这一列变成「最后写入时间」。2026-10-18 首轮 HF 抓取实测：真实新增 1411 行，
而 `inserted_at > 窗口起点` 数出 1976 行——差额全是「被更新」的旧行。

这组用例盯三件事：
  ① 更新既有行时 `inserted_at` 保持不变，其它字段照常刷新；
  ② 其它字段确实刷新了（否则用例会因为「什么都没更新」而假通过）；
  ③ 标签是整体替换的快照（先 DELETE 再插入），行为与本 issue 无关，用一条用例钉住。
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest

from src.scraper import fetch_models as fm


MODEL_ID = "acme/issue-035-model"
OLD_INSERTED_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _record(model_name: str, inserted_at: datetime) -> fm.ModelRecord:
    return fm.ModelRecord(
        model_id=MODEL_ID,
        provider="acme",
        model_name=model_name,
        description="",
        tags=["llm"],
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        downloads=10,
        likes=1,
        model_card_url="https://example.test/acme",
        inserted_at=inserted_at,
        is_open_source=True,
        price=None,
        huggingface_rank=None,
    )


@pytest.fixture()
def clean_row(db_url: str):
    """先删掉本次要用的行，避免上一个用例残留让断言失真。"""
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_tags WHERE model_id = %s", (MODEL_ID,))
            cur.execute("DELETE FROM models WHERE model_id = %s", (MODEL_ID,))
        conn.commit()
    yield db_url
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_tags WHERE model_id = %s", (MODEL_ID,))
            cur.execute("DELETE FROM models WHERE model_id = %s", (MODEL_ID,))
        conn.commit()


def test_update_keeps_original_inserted_at(clean_row: str):
    later = datetime(2026, 9, 9, 9, 9, 9, tzinfo=timezone.utc)
    with psycopg.connect(clean_row) as conn:
        _processed, inserted = fm.save_models(
            conn, "acme", [_record("first name", OLD_INSERTED_AT)], started_at=later
        )
        conn.commit()
        assert inserted == 1

        _processed, inserted = fm.save_models(
            conn, "acme", [_record("second name", later)], started_at=later
        )
        conn.commit()
        assert inserted == 0, "同一个 model_id 再写一次应当算更新，不是新增"

        with conn.cursor() as cur:
            cur.execute(
                "SELECT model_name, inserted_at FROM models WHERE model_id = %s",
                (MODEL_ID,),
            )
            model_name, inserted_at = cur.fetchone()

    assert model_name == "second name", "其它字段必须照常刷新，否则这条用例证明不了什么"
    assert inserted_at == OLD_INSERTED_AT, "inserted_at 是首次入库时间，不该被更新覆盖"


def test_model_tags_are_replaced_wholesale(clean_row: str):
    """标签是当前快照：每次写入先删后插，旧标签不会残留。"""
    later = datetime(2026, 9, 9, 9, 9, 9, tzinfo=timezone.utc)
    with psycopg.connect(clean_row) as conn:
        fm.save_models(conn, "acme", [_record("first name", OLD_INSERTED_AT)], started_at=later)
        conn.commit()

        second = _record("second name", later)
        second.tags = ["other"]
        fm.save_models(conn, "acme", [second], started_at=later)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT tag FROM model_tags WHERE model_id = %s", (MODEL_ID,))
            tags = sorted(row[0] for row in cur.fetchall())

    assert tags == ["other"], "旧标签应随重写被清掉，只留当前快照"
