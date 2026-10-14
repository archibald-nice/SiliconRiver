"""API 契约与回归测试。

大部分用例**不需要数据库**，只检查路由表与纯函数；需要数据的少数几个用
`client` fixture（见 conftest.py），没配 TEST_DATABASE_URL 时自动跳过。

这里锁住的三个历史 bug（均已在本地用 TestClient 实测复现过）：
  1. `/api/models/{model_id:path}` 注册顺序靠前，吃掉了后面的固定路径路由；
  2. 真实 model_id 含斜杠（`provider/name`），`{model_id}` 转换器匹配不到；
  3. `POST /api/arena/scores/batch` 是公开无鉴权的写接口。
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest
from fastapi.routing import APIRoute

import backend.main as main

# 项目里允许存在的 POST 路由白名单。
# 这两个虽然用 POST，但都是**只读**查询：之所以用 POST，是因为 model_id 形如
# "provider/name" 含斜杠，放进路径参数匹配不到，只能走请求体。
READ_ONLY_POST_ROUTES = {
    "/api/models/analysis",
    "/api/models/analysis-with-scores",
}


@pytest.fixture()
def bare_client():
    """不接触数据库的客户端：只用于 /health、CORS、路由表这类检查。"""
    from fastapi.testclient import TestClient

    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def _api_routes() -> list[APIRoute]:
    return [
        route
        for route in main.app.routes
        if isinstance(route, APIRoute) and route.path.startswith(("/api", "/health"))
    ]


# --------------------------------------------------------------------------
# 路由表结构
# --------------------------------------------------------------------------

def test_path_catch_all_route_is_registered_last():
    """兜底路由必须是 /api/models/* 里最后一个 GET，否则会吃掉固定路径路由。

    这正是不用 {model_id} 而用 {model_id:path} 时必须守住的顺序不变量。
    """
    get_model_paths = [
        route.path
        for route in _api_routes()
        if "GET" in route.methods and route.path.startswith("/api/models")
    ]
    assert "/api/models/{model_id:path}" in get_model_paths
    assert get_model_paths[-1] == "/api/models/{model_id:path}", (
        f"兜底路由不在最后，实际顺序：{get_model_paths}"
    )


def test_no_fixed_path_route_is_shadowed_by_catch_all():
    """所有固定路径（不含参数）的 /api/models 路由都必须排在兜底路由之前。"""
    routes = [
        route.path
        for route in _api_routes()
        if route.path.startswith("/api/models")
    ]
    catch_all_index = routes.index("/api/models/{model_id:path}")
    for path in routes[:catch_all_index]:
        assert "{" not in path, f"固定路径 {path} 被排到了兜底路由之后"


def test_no_unauthenticated_write_routes():
    """API 层不应该存在任何非白名单的 POST/PUT/DELETE 路由。"""
    offenders = [
        (sorted(route.methods), route.path)
        for route in _api_routes()
        if route.methods & {"POST", "PUT", "PATCH", "DELETE"}
        and route.path not in READ_ONLY_POST_ROUTES
    ]
    assert not offenders, f"出现了预期之外的写路由：{offenders}"


def test_arena_batch_endpoint_is_gone():
    """公开无鉴权的批量写接口必须不存在。

    等价能力已挪到 scripts/update_arena_scores.py（本机 CLI）。
    """
    paths = {route.path for route in _api_routes()}
    assert "/api/arena/scores/batch" not in paths
    for route in _api_routes():
        assert not (route.path.startswith("/api/arena") and "POST" in route.methods)


# --------------------------------------------------------------------------
# 同步/异步：psycopg 是同步驱动，除头像代理外都必须是同步函数
# --------------------------------------------------------------------------

def test_only_avatar_route_is_async():
    """纯数据库路由必须是同步 def，交给 FastAPI 线程池执行。

    若退回 async def，同步 psycopg 调用会阻塞事件循环。
    """
    async_paths = {
        route.path
        for route in _api_routes()
        if inspect.iscoroutinefunction(route.endpoint)
    }
    assert async_paths == {"/api/providers/{provider_id}/avatar"}, (
        f"异步路由集合变了：{async_paths}"
    )


def test_get_db_is_sync_generator():
    """连接依赖也必须是同步生成器，否则建连接会阻塞事件循环。"""
    assert not inspect.iscoroutinefunction(main.get_db)
    assert inspect.isgeneratorfunction(main.get_db)


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------

def test_cors_allows_local_dev_origin(bare_client):
    response = bare_client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unknown_origin(bare_client):
    response = bare_client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") is None


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------

def test_health_does_not_touch_database(bare_client):
    """健康检查必须能在数据库挂掉时依然返回 200（负载均衡器依赖它）。"""
    response = bare_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, []),
        ("", []),
        ("   ", []),
        ("llm,vision", ["llm", "vision"]),
        (" llm , vision ", ["llm", "vision"]),
        ('["llm", "vision"]', ["llm", "vision"]),
        # 坏 JSON 要退化成逗号切分，而不是抛异常
        ('["llm", broken', ['["llm"', "broken"]),
    ],
)
def test_parse_tags(raw, expected):
    assert main._parse_tags(raw) == expected


def test_timeline_window_for_explicit_year():
    start, end, label = main._calculate_timeline_window(preset="30d", year=2024)
    assert start == datetime(2024, 1, 1)
    assert end == datetime(2024, 12, 31, 23, 59, 59)
    assert label == "2024年"


def test_timeline_window_preset_all_starts_at_epoch():
    start, end, label = main._calculate_timeline_window(preset="all", year=None)
    assert start == datetime(1970, 1, 1)
    assert label == "全部"
    assert end >= start


def test_timeline_window_labels_follow_preset():
    _, _, label_30d = main._calculate_timeline_window(preset="30d", year=None)
    _, _, label_6m = main._calculate_timeline_window(preset="6m", year=None)
    _, _, label_1y = main._calculate_timeline_window(preset="1y", year=None)
    assert label_30d == "近30天"
    assert label_6m == "近半年"
    assert label_1y == "今年"


def test_timeline_window_6m_spans_182_days():
    start, end, _ = main._calculate_timeline_window(preset="6m", year=None)
    assert timedelta(days=181) < (end - start) <= timedelta(days=183)


def test_timeline_window_returns_naive_datetimes():
    """必须是 naive datetime。

    models.created_at 是 `timestamp without time zone`；一旦带上 tzinfo，
    Postgres 会按会话时区换算，时间轴窗口边界就会漂移。
    """
    for preset in ("30d", "6m", "1y", "all"):
        start, end, _ = main._calculate_timeline_window(preset=preset, year=None)
        assert start.tzinfo is None, f"preset={preset} 的 start 带了时区"
        assert end.tzinfo is None, f"preset={preset} 的 end 带了时区"
    start, end, _ = main._calculate_timeline_window(preset="30d", year=2024)
    assert start.tzinfo is None and end.tzinfo is None


# --------------------------------------------------------------------------
# 需要数据库的行为回归（含斜杠的 model_id）
# --------------------------------------------------------------------------

def test_model_lookup_with_slash_in_id(client):
    response = client.get("/api/models/acme/alpha-1")
    assert response.status_code == 200
    assert response.json()["model_id"] == "acme/alpha-1"


def test_analysis_with_scores_reachable_for_slash_id(client):
    """回归：这个端点曾被兜底路由吃掉，对任何真实 model_id 都 404。"""
    response = client.post("/api/models/analysis-with-scores", json={"model_id": "acme/alpha-1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_id"] == "acme/alpha-1"
    assert body["is_milestone"] is True
    assert body["arena_score"]["has_score"] is True
    # 回归：has_score=True 时曾经漏传 model_id，导致汇总里的 model_id 永远是 null
    assert body["arena_score"]["model_id"] == "acme/alpha-1"
    assert body["arena_score"]["combined_score"] == pytest.approx(635.85)


def test_analysis_with_scores_404_for_unknown_model(client):
    response = client.post("/api/models/analysis-with-scores", json={"model_id": "acme/nope"})
    assert response.status_code == 404


def test_arena_scores_reachable_for_slash_id(client):
    """回归：{model_id} 转换器不匹配斜杠，这个端点曾对真实 ID 全部 404。"""
    response = client.get("/api/arena/scores/acme/alpha-1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_id"] == "acme/alpha-1"
    assert body["has_score"] is True
    assert body["combined_score"] == pytest.approx(635.85)
    assert set(body["sources"]) == {"swe-bench", "lmsys"}


def test_arena_scores_returns_empty_summary_for_model_without_scores(client):
    response = client.get("/api/arena/scores/acme/beta-2")
    assert response.status_code == 200
    assert response.json()["has_score"] is False


def test_analysis_lookup_returns_404_when_absent(client):
    response = client.post("/api/models/analysis", json={"model_id": "acme/beta-2"})
    assert response.status_code == 404


def test_analysis_lookup_returns_row_when_present(client):
    response = client.post("/api/models/analysis", json={"model_id": "acme/alpha-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["key_features"] == ["fast"]
    assert body["is_milestone"] is True


def test_timeline_returns_all_models_for_preset_all(client):
    response = client.get("/api/timeline", params={"preset": "all", "page_size": 50})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["label"] == "全部"


def test_timeline_rejects_page_size_below_minimum(client):
    response = client.get("/api/timeline", params={"preset": "all", "page_size": 5})
    assert response.status_code == 422


def test_timeline_rejects_unknown_preset(client):
    response = client.get("/api/timeline", params={"preset": "bogus"})
    assert response.status_code == 422


def test_timeline_filters_by_provider(client):
    response = client.get("/api/timeline", params={"preset": "all", "provider": "globex", "page_size": 50})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["model_id"] == "globex/gamma-3"


def test_timeline_filters_by_open_source(client):
    response = client.get("/api/timeline", params={"preset": "all", "open_source": "true", "page_size": 50})
    assert response.status_code == 200
    ids = {item["model_id"] for item in response.json()["items"]}
    assert ids == {"acme/alpha-1", "globex/gamma-3"}


def test_timeline_search_is_case_insensitive(client):
    response = client.get("/api/timeline", params={"preset": "all", "model_name": "gamma", "page_size": 50})
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_timeline_is_ordered_ascending_by_default(client):
    response = client.get("/api/timeline", params={"preset": "all", "page_size": 50})
    created = [item["created_at"] for item in response.json()["items"]]
    assert created == sorted(created)


def test_provider_stats_groups_by_provider(client):
    response = client.get("/api/stats/providers")
    assert response.status_code == 200
    stats = {row["provider"]: row["model_count"] for row in response.json()}
    assert stats == {"acme": 2, "globex": 1}


def test_analysis_stats_counts_analyzed_models(client):
    response = client.get("/api/analysis/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["total_models"] == 3
    assert body["analyzed_models"] == 1
    assert body["unanalyzed_models"] == 2


def test_analysis_tags_are_sorted_and_unique(client):
    response = client.get("/api/analysis/tags")
    assert response.status_code == 200
    tags = response.json()["tags"]
    assert tags == ["llm", "vision"]


def test_models_list_paginates(client):
    response = client.get("/api/models", params={"page": 1, "page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    second = client.get("/api/models", params={"page": 2, "page_size": 2}).json()
    assert len(second["items"]) == 1
    assert {item["model_id"] for item in body["items"]} & {
        item["model_id"] for item in second["items"]
    } == set()


def test_unknown_provider_avatar_returns_404(client):
    response = client.get("/api/providers/nope/avatar")
    assert response.status_code == 404
