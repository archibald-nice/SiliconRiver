"""ISSUE-021 回归：`total` 与 `items` 同源（一条语句）+ 两个 GET 的 `Cache-Control`。

原缺陷：`/api/models` 与 `/api/timeline` 先跑 `SELECT COUNT(*)`、再跑 `LIMIT/OFFSET`，
两条语句之间同步任务提交新数据时，客户端会拿到「total 是新快照、items 是旧快照」的组合，
分页器于是出现「总数 3、翻到第 2 页却是空的」这类错位。

验证策略：
- **结构性证据**（不需要数据库、100% 确定）：给路由喂一个只记录 SQL 的假连接，断言
  每次请求只发出 **1 条** 语句，且这条语句同时包含 `COUNT(*)` 与 `LIMIT/OFFSET`。
  语句只有一条，就不存在两条语句之间的时间窗口。
- **行为证据**（需要数据库）：两个接口都带上 `Cache-Control`；offset 翻过末尾时 total
  仍然是全量计数（这条覆盖 `count 左连接` 这个容易写回 `COUNT(*) OVER()` 的坑）。

诚实的限制：没有做「真的在语句之间插入一行」的并发竞态测试——那需要精确控制另一条
连接的执行时机，单元测试无法确定性复现；上面第 1 条才是本修复的真正保障。
"""
from __future__ import annotations

from datetime import datetime

from fastapi.responses import Response

import backend.main as main


class _RecordingCursor:
    """记录发出去的 SQL，并按固定结果行返回（模拟 cursor 上下文管理器）。"""

    def __init__(self, rows: list[dict], sink: list[tuple[str, list]]) -> None:
        self._rows = rows
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        # 归一化空白，方便断言片段（保留 `\n` 会干扰多行断言）
        self._sink.append((" ".join(sql.split()), list(params or [])))

    def fetchall(self) -> list[dict]:
        return list(self._rows)


class _RecordingConnection:
    """假的 psycopg 连接：只实现 cursor()，把语句收进 self.statements。"""

    def __init__(self, rows: list[dict]) -> None:
        self.statements: list[tuple[str, list]] = []
        self._rows = rows

    def cursor(self, row_factory=None) -> _RecordingCursor:  # noqa: ARG002 - 签名对齐真实连接
        return _RecordingCursor(self._rows, self.statements)


def _model_row(**overrides) -> dict:
    row = {
        "model_id": "acme/alpha-1",
        "provider": "acme",
        "model_name": "alpha-1",
        "description": "d",
        "tags": "[]",
        "created_at": datetime(2024, 1, 15),
        "downloads": 1,
        "likes": 2,
        "model_card_url": "https://example.com/alpha-1",
        "total": 3,
    }
    row.update(overrides)
    return row


def _timeline_row(**overrides) -> dict:
    row = _model_row(
        is_open_source=True,
        price=None,
        huggingface_rank=1,
        avatar_url=None,
        analysis_summary=None,
    )
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- 结构性证据


def test_list_models_issues_exactly_one_statement():
    conn = _RecordingConnection([_model_row(), _model_row(model_id="acme/beta-2")])
    response = Response()
    body = main.list_models(
        response=response,
        page=2,
        page_size=1,
        provider=None,
        tag=None,
        search=None,
        conn=conn,
    )

    assert len(conn.statements) == 1, f"total 与 items 必须同源，实际发出 {len(conn.statements)} 条语句"
    sql, params = conn.statements[0]
    assert "WITH filtered AS" in sql
    assert "COUNT(*) AS total" in sql
    assert "LIMIT %s OFFSET %s" in sql
    # 参数只有当页份：过滤器参数 + page_size + offset，不存在第二个 count 的参数集
    assert params == [1, 1]
    assert body.total == 3
    assert response.headers["Cache-Control"] == main.CACHE_CONTROL_MODELS


def test_timeline_issues_exactly_one_statement():
    conn = _RecordingConnection([_timeline_row()])
    response = Response()
    body = main.timeline_models(
        response=response,
        preset="all",
        year=None,
        page=1,
        page_size=50,
        sort="asc",
        provider=None,
        model_name=None,
        open_source=None,
        conn=conn,
    )

    assert len(conn.statements) == 1, f"total 与 items 必须同源，实际发出 {len(conn.statements)} 条语句"
    sql, params = conn.statements[0]
    assert "WITH filtered AS" in sql
    assert "COUNT(*) AS total" in sql
    assert "LIMIT %s OFFSET %s" in sql
    assert params == [50, 0]
    assert body.total == 3
    assert response.headers["Cache-Control"] == main.CACHE_CONTROL_TIMELINE


def test_out_of_range_page_keeps_total_via_count_left_join():
    """当页为空时 count 左连接会补一行占位行：items 空，但 total 不能丢。

    如果实现改回 `COUNT(*) OVER()`，这里会得到 total == 0，用例即失败。
    """
    conn = _RecordingConnection([{"model_id": None, "total": 7}])
    body = main.list_models(
        response=Response(),
        page=99,
        page_size=10,
        provider=None,
        tag=None,
        search=None,
        conn=conn,
    )
    assert body.items == []
    assert body.total == 7

    timeline_conn = _RecordingConnection([{"model_id": None, "total": 7}])
    timeline = main.timeline_models(
        response=Response(),
        preset="all",
        year=None,
        page=99,
        page_size=10,
        sort="asc",
        provider=None,
        model_name=None,
        open_source=None,
        conn=timeline_conn,
    )
    assert timeline.items == []
    assert timeline.total == 7


# --------------------------------------------------------------------------- 行为证据（DB）


def _parse_directives(header: str) -> dict:
    directives = {}
    for chunk in header.split(","):
        key, _, value = chunk.strip().partition("=")
        directives[key.lower()] = value or True
    return directives


def test_models_response_has_cache_control(client):
    response = client.get("/api/models", params={"page_size": 10})
    assert response.status_code == 200
    header = response.headers["cache-control"]
    assert header == main.CACHE_CONTROL_MODELS
    directives = _parse_directives(header)
    assert directives["public"] is True
    assert int(directives["max-age"]) == 60
    assert int(directives["stale-while-revalidate"]) == 300


def test_timeline_response_has_cache_control(client):
    response = client.get("/api/timeline", params={"preset": "all", "page_size": 50})
    assert response.status_code == 200
    header = response.headers["cache-control"]
    assert header == main.CACHE_CONTROL_TIMELINE


def test_timeline_max_age_is_shorter_than_models(client):
    """timeline 的 max-age 必须明显更短：窗口 end 是服务端当前时间、每次响应都在变，
    新模型入库后旧响应立刻过时；缓存太久会让「今天刚发的模型」迟迟不出现。
    """
    timeline_max_age = int(_parse_directives(main.CACHE_CONTROL_TIMELINE)["max-age"])
    models_max_age = int(_parse_directives(main.CACHE_CONTROL_MODELS)["max-age"])
    assert 0 < timeline_max_age <= 30
    assert timeline_max_age < models_max_age


def test_models_total_matches_items_for_single_page(client):
    body = client.get("/api/models", params={"page": 1, "page_size": 100}).json()
    assert body["total"] == 3
    assert len(body["items"]) == body["total"]


def test_models_filtered_total_matches_items(client):
    body = client.get("/api/models", params={"provider": "acme", "page_size": 100}).json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_models_page_past_the_end_keeps_total(client):
    body = client.get("/api/models", params={"page": 99, "page_size": 10}).json()
    assert body["total"] == 3
    assert body["items"] == []


def test_timeline_page_past_the_end_keeps_total(client):
    body = client.get(
        "/api/timeline", params={"preset": "all", "page": 99, "page_size": 10}
    ).json()
    assert body["total"] == 3
    assert body["items"] == []


def test_timeline_total_counts_models_not_join_rows(client):
    """alpha-1 有分析行、providers 也有对应行，total 仍要数模型行（3），不是宽行。"""
    body = client.get("/api/timeline", params={"preset": "all", "page_size": 50}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
