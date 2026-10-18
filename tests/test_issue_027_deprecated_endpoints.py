"""ISSUE-027 回归：已下线的 `/api/analysis/stats` 与 `/api/analysis/tags` 必须真的消失。

这两个端点是旧版分析页的遗留接口，前端早已不再调用（统计数据走
`/api/stats/providers`，即 `frontend` 里的 `fetchStats`）。只删路由不够：还要确认
处理函数与 `AnalysisStats` 模型一并清掉，避免留下「看得见但没挂路由」的死代码。
"""
from __future__ import annotations

import pytest

import backend.main as main
import models as models_module

DEPRECATED_PATHS = ("/api/analysis/stats", "/api/analysis/tags")


@pytest.fixture()
def bare_client():
    """不接触数据库：404 由路由匹配决定，不会进到查库逻辑。"""
    from fastapi.testclient import TestClient

    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def _registered_paths() -> set[str]:
    return {getattr(route, "path", "") for route in main.app.routes}


def test_deprecated_endpoints_are_not_registered():
    paths = _registered_paths()
    for path in DEPRECATED_PATHS:
        assert path not in paths, f"{path} 应已删除"


def test_deprecated_endpoints_return_404(bare_client):
    """FastAPI 默认 404（detail "Not Found"），而不是之前的 200 + 数据。"""
    for path in DEPRECATED_PATHS:
        response = bare_client.get(path)
        assert response.status_code == 404, path
        assert response.json()["detail"] == "Not Found"


def test_deprecated_handlers_are_removed():
    """处理函数不能留成孤儿（路由删了、函数还在 = 下次有人误以为仍可用）。"""
    assert not hasattr(main, "get_analysis_stats")
    assert not hasattr(main, "get_analysis_tags")


def test_analysis_stats_model_is_removed():
    """`AnalysisStats` 是这两个端点的响应模型，随端点一起删掉。"""
    assert not hasattr(models_module, "AnalysisStats")


def test_provider_stats_endpoint_is_untouched(client):
    """`fetchStats` 真正走的是 /api/stats/providers —— 删除不能波及它。"""
    response = client.get("/api/stats/providers")
    assert response.status_code == 200
    stats = {row["provider"]: row["model_count"] for row in response.json()}
    assert stats == {"acme": 2, "globex": 1}


def test_analysis_endpoint_still_available(client):
    """分析相关的能力仍由 POST /api/models/analysis 提供。"""
    response = client.post("/api/models/analysis", json={"model_id": "acme/alpha-1"})
    assert response.status_code == 200
