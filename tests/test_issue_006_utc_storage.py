"""ISSUE-006 回归：时间列统一 UTC（`timestamptz`）存储。

原缺陷：`models.created_at` 是 `timestamp without time zone`（值语义是 UTC 但没标记），
`models.inserted_at` / `sync_log.started_at` / `sync_log.finished_at` /
`model_tags.inserted_at` 干脆是 text。API 于是序列化出 `"2026-10-16T04:00:00"`
这种**不带偏移**的字符串，浏览器 `new Date()` 按访问者本地时区解析 → 时间轴整体偏移。

本文件用真实数据库钉住三件事：
1. schema 层：那五列必须是 `timestamp with time zone`（新建库走 `scripts/init_db.py`）；
2. 序列化层：`/api/models` 返回的 `created_at` 必须带 `+00:00`（或 `Z`）且时刻不变；
3. 查询层：`year=` 窗口按 **UTC 年**切片——`2024-12-31T23:00Z` 属于 2024，不属于 2025。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
import pytest

import backend.main as main

UTC = timezone.utc

# ISSUE-006 改过的列：必须是 timestamptz
MIGRATED_COLUMNS = [
    ("models", "created_at"),
    ("models", "inserted_at"),
    ("sync_log", "started_at"),
    ("sync_log", "finished_at"),
    ("model_tags", "inserted_at"),
]

# 本来就正确的列：一并钉住，防止「修 A 弄坏 B」
ALREADY_TIMESTAMPTZ_COLUMNS = [
    ("providers", "created_at"),
    ("providers", "updated_at"),
    ("model_analysis", "analyzed_at"),
    ("model_analysis", "updated_at"),
    ("model_arena_info", "created_at"),
    ("model_arena_info", "updated_at"),
]

# 与 scripts/init_db.py 对齐：这两列不仅要改类型，还要有 CURRENT_TIMESTAMP 默认值
COLUMNS_WITH_DEFAULT = [("models", "inserted_at"), ("model_tags", "inserted_at")]


def _column_meta(db_url: str, table: str, column: str) -> tuple[str, str | None]:
    """直接查 information_schema，返回 (data_type, column_default)。"""
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_type, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        row = cur.fetchone()
    assert row is not None, f"{table}.{column} 不存在（schema 没建好？）"
    return row[0], row[1]


def _insert_model(db_url: str, model_id: str, created_at: datetime) -> None:
    """插入一条只用于本文件断言的模型（调用方负责删）。"""
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO models
                (model_id, provider, model_name, description, tags, created_at,
                 downloads, likes, model_card_url, inserted_at, is_open_source,
                 price, huggingface_rank)
            VALUES (%s, 'acme', %s, 'utc storage probe', '["llm"]',
                    %s, 0, 0, 'https://example.com/probe', %s, TRUE, NULL, NULL)
            """,
            (model_id, model_id.split("/")[-1], created_at, created_at),
        )


def _delete_model(db_url: str, model_id: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM model_tags WHERE model_id = %s", (model_id,))
        cur.execute("DELETE FROM model_analysis WHERE model_id = %s", (model_id,))
        cur.execute("DELETE FROM models WHERE model_id = %s", (model_id,))


def _parse_iso(value: str) -> datetime:
    """把 API 返回的时间串解析回 datetime（吞掉 `Z` 写法）。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


PROBE_MODEL_ID = "acme/utc-probe-2025"
PROBE_MODEL_CREATED_AT = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)


@contextmanager
def _probe_model(db_url: str, model_id: str = PROBE_MODEL_ID, created_at: datetime = PROBE_MODEL_CREATED_AT):
    """在**用例体内**插入探针模型并保证清理。

    为什么不用 fixture：fixture 的插入发生在 `client` fixture 建好之后、用例体之前
    这一小段窗口里；全量跑时这段窗口里如果有别的东西重置库（或并发跑同一测试库），
    探针模型会消失，用例报"查不到"而不是暴露真问题。放进用例体内窗口最小。
    """
    _insert_model(db_url, model_id, created_at)
    try:
        yield model_id
    finally:
        _delete_model(db_url, model_id)


# ---------------------------------------------------------------------------
# 1. schema：列类型与默认值
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table, column", MIGRATED_COLUMNS)
def test_issue006_time_column_is_timestamptz(seeded_db, table, column):
    """`init_db.py` 建出来的时间列必须是 `timestamp with time zone`。

    反向断言的意义：`timestamp without time zone` 会把 UTC 时刻存成"没有时区的
    墙上时间"，读出来无法区分 UTC 与本地时间——这正是 ISSUE-006 的根因。
    """
    data_type, _ = _column_meta(seeded_db, table, column)
    assert data_type == "timestamp with time zone", f"{table}.{column} 的 data_type={data_type!r}"


@pytest.mark.parametrize("table, column", ALREADY_TIMESTAMPTZ_COLUMNS)
def test_issue006_untouched_time_columns_stay_timestamptz(seeded_db, table, column):
    """这次没动的列不能被顺手改坏（它们本来就是 timestamptz）。"""
    data_type, _ = _column_meta(seeded_db, table, column)
    assert data_type == "timestamp with time zone"


@pytest.mark.parametrize("table, column", COLUMNS_WITH_DEFAULT)
def test_issue006_inserted_at_has_current_timestamp_default(seeded_db, table, column):
    """入库时间列要保留 `CURRENT_TIMESTAMP` 默认值（手写 INSERT 时常省略该列）。"""
    _, default = _column_meta(seeded_db, table, column)
    assert default is not None, f"{table}.{column} 没有默认值"
    assert "CURRENT_TIMESTAMP" in default.upper()


def test_issue006_sync_log_round_trips_as_aware_datetime(seeded_db):
    """`sync_log` 写 aware datetime、读回来仍是 aware（旧实现是 text + isoformat 字符串）。"""
    started = datetime(2025, 6, 3, 12, 0, tzinfo=UTC)
    finished = datetime(2025, 6, 3, 12, 0, 5, 123456, tzinfo=UTC)
    with psycopg.connect(seeded_db, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_log (provider, started_at, finished_at, status, processed, inserted)
            VALUES ('probe', %s, %s, 'success', 3, 2)
            """,
            (started, finished),
        )
        cur.execute(
            "SELECT started_at, finished_at FROM sync_log WHERE provider = 'probe'"
        )
        got_started, got_finished = cur.fetchone()
        cur.execute("DELETE FROM sync_log WHERE provider = 'probe'")

    assert got_started.tzinfo is not None, "started_at 读回来必须是 aware datetime"
    assert got_finished.tzinfo is not None, "finished_at 读回来必须是 aware datetime"
    assert got_started == started
    assert got_finished == finished


# ---------------------------------------------------------------------------
# 2. 序列化：API 返回带偏移，时刻不变
# ---------------------------------------------------------------------------


def test_issue006_models_api_returns_utc_offset(client, ensure_seeded):
    """`/api/models` 必须返回带 `+00:00` / `Z` 的串，且解析回来仍是同一个时刻。

    这是缺陷的直接表现面：不带偏移的 `2025-06-03T12:00:00` 会被浏览器按本地时区
    解析成 UTC+8 的 12:00（= 04:00Z），整条时间轴偏移 8 小时。
    """
    with _probe_model(ensure_seeded) as model_id:
        response = client.get("/api/models", params={"page_size": 100})
        assert response.status_code == 200, response.text
        item = next(
            (row for row in response.json()["items"] if row["model_id"] == model_id), None
        )
        assert item is not None, "刚插入的探针模型没有出现在 /api/models 里"

        raw = item["created_at"]
        assert isinstance(raw, str)
        assert raw.endswith(("+00:00", "Z")), f"created_at 不带 UTC 偏移：{raw!r}"
        assert _parse_iso(raw) == PROBE_MODEL_CREATED_AT


def test_issue006_model_detail_api_returns_utc_offset(client, ensure_seeded):
    """单条详情接口（`{model_id:path}`）同样不能退化成 naive 串。"""
    with _probe_model(ensure_seeded) as model_id:
        response = client.get(f"/api/models/{model_id}")
        assert response.status_code == 200, response.text
        raw = response.json()["created_at"]
        assert raw.endswith(("+00:00", "Z")), f"created_at 不带 UTC 偏移：{raw!r}"
        assert _parse_iso(raw) == PROBE_MODEL_CREATED_AT


# ---------------------------------------------------------------------------
# 3. 查询窗口：年份按 UTC 年切
# ---------------------------------------------------------------------------


def test_issue006_year_window_slices_by_utc_year(ensure_seeded):
    """`year=2025` 命中 UTC 2025 的模型，不命中 `2024-12-31T23:00Z`。

    后一条正是时区边界的经典陷阱：它在**本地**（UTC+8）是 2025-01-01 07:00，
    但按 UTC 年属于 2024。窗口边界必须是 aware UTC，否则 Postgres 会按会话时区
    解释 naive 边界，结果随部署机器时区变化。
    """
    inside = "acme/utc-year-inside"
    edge = "acme/utc-year-edge"
    _insert_model(ensure_seeded, inside, datetime(2025, 1, 1, 0, 0, tzinfo=UTC))
    _insert_model(ensure_seeded, edge, datetime(2024, 12, 31, 23, 0, tzinfo=UTC))
    try:
        from fastapi.testclient import TestClient

        monkeypatch_target = main
        original = monkeypatch_target.DATABASE_URL
        monkeypatch_target.DATABASE_URL = ensure_seeded
        try:
            with TestClient(main.app, raise_server_exceptions=False) as probe_client:
                response_2025 = probe_client.get(
                    "/api/timeline", params={"year": 2025, "page_size": 100}
                )
                response_2024 = probe_client.get(
                    "/api/timeline", params={"year": 2024, "page_size": 100}
                )
        finally:
            monkeypatch_target.DATABASE_URL = original
    finally:
        _delete_model(ensure_seeded, inside)
        _delete_model(ensure_seeded, edge)

    assert response_2025.status_code == 200, response_2025.text
    assert response_2024.status_code == 200, response_2024.text
    ids_2025 = {item["model_id"] for item in response_2025.json()["items"]}
    ids_2024 = {item["model_id"] for item in response_2024.json()["items"]}

    assert inside in ids_2025
    assert edge not in ids_2025, "UTC 2024 的模型不应该落进 2025 年窗口"
    assert edge in ids_2024
    assert inside not in ids_2024

    # 窗口边界本身也要带 UTC 偏移
    body = response_2025.json()
    assert _parse_iso(body["start"]) == datetime(2025, 1, 1, tzinfo=UTC)
    assert _parse_iso(body["end"]) == datetime(2025, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
