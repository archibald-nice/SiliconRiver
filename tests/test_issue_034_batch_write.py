"""ISSUE-034：批量写必须与逐行写结果完全等价。

批量写把「每模型 3–4 次跨洋往返」压成「每批 3 条语句」，是每日同步从 64 分钟
降到分钟级的关键。但优化不能改变数据语义，所以这里用**同一批输入分别跑两条路径**，
逐字段比对结果与计数：

  ① 新增行、更新行都要一致（含 `RETURNING (xmax = 0)` 的 inserted 计数）；
  ② 大小写归一（`acme/BATCH-Alpha` → 库里既有 `acme/batch-alpha`）一致；
  ③ 同一批里两条记录落到同一个 target 时，后写覆盖先写且不报
     "ON CONFLICT DO UPDATE command cannot affect row a second time"；
  ④ 标签是「当前快照」：整批先删后插，与逐行写结果一致。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg
import pytest

from src.scraper import fetch_models as fm
from src.scraper import fetch_models_openrouter as bm

PREFIX = "acme/batch-"
EXISTING_ID = "acme/batch-alpha"  # 先以正形入库，用来触发大小写归一
NEW_ID = "acme/batch-beta"
VARIANT_ID = "acme/BATCH-ALPHA"

FIXED_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def _record(
    model_id: str,
    *,
    name: str,
    tags: list[str],
    downloads: int = 1,
    description: str = "desc",
    price: dict | None = None,
    created_at: datetime | None = None,
) -> fm.ModelRecord:
    return fm.ModelRecord(
        model_id=model_id,
        provider="acme",
        model_name=name,
        description=description,
        tags=tags,
        created_at=created_at or FIXED_NOW,
        downloads=downloads,
        likes=2,
        model_card_url="https://example.test/card",
        inserted_at=LATER,
        is_open_source=True,
        price=price,
        huggingface_rank=None,
    )


def _clean(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_tags WHERE lower(model_id) LIKE %s", (PREFIX + "%",))
            cur.execute("DELETE FROM sync_log WHERE provider = 'acme'")
            cur.execute("DELETE FROM models WHERE lower(model_id) LIKE %s", (PREFIX + "%",))
        conn.commit()


@pytest.fixture()
def clean_db(db_url: str):
    _clean(db_url)
    yield db_url
    _clean(db_url)


def _seed_existing(db_url: str) -> None:
    """先说库里已有一条正形的 alpha，后面用变体 id 去撞它。"""
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO models (model_id, provider, model_name, description, tags,
                                    created_at, model_card_url, inserted_at, source)
                VALUES (%s, 'acme', 'Alpha old', 'old', '[]', %s,
                        'https://example.test/card', %s, 'huggingface')
                """,
                (EXISTING_ID, FIXED_NOW, FIXED_NOW),
            )
        conn.commit()


def _snapshot(db_url: str) -> tuple[list[tuple], list[tuple]]:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT model_id, provider, model_name, description, tags, created_at,
                       downloads, likes, model_card_url, is_open_source, price,
                       huggingface_rank, source, inserted_at
                FROM models WHERE lower(model_id) LIKE %s ORDER BY lower(model_id)
                """,
                (PREFIX + "%",),
            )
            models = cur.fetchall()
            cur.execute(
                """
                SELECT model_id, tag FROM model_tags
                WHERE lower(model_id) LIKE %s ORDER BY lower(model_id), tag
                """,
                (PREFIX + "%",),
            )
            tags = cur.fetchall()
    return models, tags


def _records() -> list[fm.ModelRecord]:
    return [
        _record(VARIANT_ID, name="Alpha new", tags=["llm", "chat"], downloads=99),
        _record(NEW_ID, name="Beta", tags=["llm"], price={"prompt": "0.0000005"}),
        # 同一批里第二次出现同一个 target（大小写不同但归一后相同），应当后者生效
        _record(EXISTING_ID, name="Alpha final", tags=["llm", "final"], downloads=123),
    ]


def _run(db_url: str, *, batch: bool) -> tuple[int, int]:
    with psycopg.connect(db_url) as conn:
        timer = fm.StageTimer("write")
        timer.begin("write")
        result = fm.save_models(conn, "acme", _records(), started_at=FIXED_NOW)
        timer.stop()
    return result


def test_batch_and_rowwise_produce_identical_rows(clean_db: str, monkeypatch):
    _seed_existing(clean_db)
    monkeypatch.setenv("SCRAPER_BATCH_WRITE", "0")
    rowwise_counts = _run(clean_db, batch=False)
    rowwise_state = _snapshot(clean_db)

    _clean(clean_db)
    _seed_existing(clean_db)
    monkeypatch.setenv("SCRAPER_BATCH_WRITE", "1")
    batch_counts = _run(clean_db, batch=True)
    batch_state = _snapshot(clean_db)

    assert batch_counts == rowwise_counts, "插入/处理计数必须一致（xmax 判新增）"
    assert batch_state == rowwise_state, "两条路径落库结果必须逐字段一致"

    # 归一到既有正形 id，且同批后写覆盖先写
    rows, tags = batch_state
    assert [row[0] for row in rows] == [EXISTING_ID, NEW_ID]
    alpha = rows[0]
    assert alpha[2] == "Alpha final", "同批同 target 应后者覆盖前者"
    assert alpha[6] == 123
    assert (EXISTING_ID, "final") in tags
    assert (EXISTING_ID, "llm") in tags
    assert (EXISTING_ID, "chat") not in tags, "标签是当前快照，旧标签应被清掉"


def test_batch_records_sync_log_once(clean_db: str, monkeypatch):
    _seed_existing(clean_db)
    monkeypatch.setenv("SCRAPER_BATCH_WRITE", "1")
    _run(clean_db, batch=True)
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT processed, inserted, status FROM sync_log WHERE provider = 'acme'"
            )
            rows = cur.fetchall()
    assert len(rows) == 1, "一批只写一条 sync_log"
    processed, inserted, status = rows[0]
    assert processed == 3
    assert inserted == 1  # 只有 beta 是新增；变体与正形都命中既有 alpha
    assert status == "success"


def test_batch_split_into_multiple_chunks(clean_db: str, monkeypatch):
    """批大小小于记录数时按块切分，结果仍与一次性写完一致。"""
    _seed_existing(clean_db)
    monkeypatch.setenv("SCRAPER_BATCH_WRITE", "1")
    monkeypatch.setenv("SCRAPER_BATCH_SIZE", "2")
    _run(clean_db, batch=True)
    rows, tags = _snapshot(clean_db)
    assert [row[0] for row in rows] == [EXISTING_ID, NEW_ID]
    assert (NEW_ID, "llm") in tags


def test_batch_price_jsonb_roundtrip(clean_db: str, monkeypatch):
    _seed_existing(clean_db)
    monkeypatch.setenv("SCRAPER_BATCH_WRITE", "1")
    _run(clean_db, batch=True)
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT price FROM models WHERE model_id = %s", (NEW_ID,))
            price = cur.fetchone()[0]
    assert json.loads(json.dumps(price, default=str)) is not None
    assert price["prompt"] == "0.0000005"


def test_batch_sql_keeps_source_and_guard_semantics():
    """批量 SQL 必须保留逐行版的两条语义：source 只认首个已知值、时间列不被覆盖。"""
    for sql in (fm.BATCH_UPSERT_SQL, bm.OR_BATCH_UPSERT_SQL):
        assert "source = COALESCE(NULLIF(models.source, 'unknown'), EXCLUDED.source)" in sql
        assert "inserted_at" in sql.split("ON CONFLICT")[0]
    assert "inserted_at = EXCLUDED" not in fm.BATCH_UPSERT_SQL
    # OR 侧：空简介/空标签/发布时间不得覆盖 HF 行
    assert "WHEN COALESCE(EXCLUDED.description, '') = '' THEN models.description" in bm.OR_BATCH_UPSERT_SQL
    assert "WHEN EXCLUDED.tags = '[]' THEN models.tags" in bm.OR_BATCH_UPSERT_SQL
    assert "created_at = COALESCE(models.created_at, EXCLUDED.created_at)" in bm.OR_BATCH_UPSERT_SQL
