"""ISSUE-022 回归：区分「未定义的 /api/models/* 子路径」与「模型不存在」。

原缺陷：兜底 `@app.get("/api/models/{model_id:path}")` 会把 `/api/models/analysis`
（其实是 POST 接口，方法用错）和 `/api/models/anything/typo`（拼错的路径）都当成
model_id 去查库，统一回 `404 {"detail": "Model not found"}`——排障时分不清是
「接口不存在」「方法不对」还是「模型名写错」，非常误导。

修复后的语义：
- `GET /api/models/analysis`、`GET /api/models/analysis-with-scores` → **405** + `Allow: POST`
- 单段路径（`/api/models/typo`）→ 404，detail 以 `Unknown API path` 开头
- 多段、但首段命名空间在库里从没出现过（`/api/models/anything/typo`）→ 404 `Unknown API path`
- 多段、命名空间存在但模型名写错（`/api/models/acme/nope`）→ 404 `Model not found`
- 真实模型、固定路径（`/analyzed`）与 POST 接口的行为保持不变

同时锁住路由顺序：新增的固定路径必须排在兜底之前，否则 `:path` 会把它们吃掉。
"""
from __future__ import annotations

import pytest

import backend.main as main

CATCH_ALL_PATH = "/api/models/{model_id:path}"


@pytest.fixture()
def bare_client():
    """不接触数据库的客户端：405 与单段路径的分支在查库之前就返回了。"""
    from fastapi.testclient import TestClient

    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def _get_model_get_paths() -> list[str]:
    """按注册顺序列出 /api/models 前缀的 GET 路由路径。"""
    ordered = []
    for route in main.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if path.startswith("/api/models") and "GET" in methods:
            ordered.append(path)
    return ordered


def test_method_mismatch_paths_return_405_not_model_not_found(bare_client):
    """方法用错不是「模型不存在」：405 且带 Allow 头。"""
    for path in ("/api/models/analysis", "/api/models/analysis-with-scores"):
        response = bare_client.get(path)
        assert response.status_code == 405, path
        body = response.json()
        assert body["detail"].startswith("Method Not Allowed")
        assert f"POST {path}" in body["detail"]
        assert response.headers["allow"] == "POST"


def test_unknown_single_segment_path_is_not_model_not_found(bare_client):
    """模型 ID 一定带斜杠（组织/模型名），单段路径不可能是模型 → 未知路径。"""
    response = bare_client.get("/api/models/typo")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail != "Model not found"
    assert detail.startswith("Unknown API path")


def test_unknown_namespace_path_is_not_model_not_found(client):
    """/api/models/anything/typo：首段命名空间不存在 → 未知路径，而非模型不存在。"""
    response = client.get("/api/models/anything/typo")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail != "Model not found"
    assert detail.startswith("Unknown API path")
    # 提示里带上首段，便于调用方看出错在哪一级
    assert "anything" in detail


def test_missing_model_under_known_namespace_is_model_not_found(client):
    """命名空间真实存在（acme 下有模型）→ 确实是模型名写错，保持原 detail。"""
    response = client.get("/api/models/acme/no-such-model")
    assert response.status_code == 404
    assert response.json()["detail"] == "Model not found"


def test_real_model_detail_still_works(client):
    """收窄兜底不能影响真实模型的详情接口（含斜杠 model_id）。"""
    response = client.get("/api/models/acme/alpha-1")
    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "acme/alpha-1"
    assert body["provider"] == "acme"
    assert body["tags"] == ["llm"]


def test_fixed_path_analyzed_still_works(client):
    """/api/models/analyzed 是固定路径，不能被新增的兜底分支吃掉。"""
    response = client.get("/api/models/analyzed", params={"page_size": 50})
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_post_analysis_still_works_after_405_routes(client):
    """为 GET 注册的 405 路由不能挡住同名路径的 POST。"""
    response = client.post("/api/models/analysis", json={"model_id": "acme/alpha-1"})
    assert response.status_code == 200
    assert response.json()["model_id"] == "acme/alpha-1"


def test_new_fixed_routes_are_registered_before_catch_all():
    """路由不变量：新增的 GET /api/models/<固定路径> 必须排在兜底之前。

    这是 ISSUE-022 修复方式本身的前提——顺序反了，`:path` 会把它们全部吃掉，
    405 与 Unknown API path 都无从谈起。
    """
    paths = _get_model_get_paths()
    assert paths[-1] == CATCH_ALL_PATH, f"兜底必须是最后一个 GET 路由，实际: {paths}"
    for fixed in ("/api/models/analysis", "/api/models/analysis-with-scores", "/api/models/analyzed"):
        assert fixed in paths, f"{fixed} 未注册为 GET 路由"
        assert paths.index(fixed) < paths.index(CATCH_ALL_PATH)
