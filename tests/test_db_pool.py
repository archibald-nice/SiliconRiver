"""数据库连接池行为测试。

需要 TEST_DATABASE_URL（见 conftest.py）。

锁住的行为：
  1. 请求之间**复用**连接，而不是每次新建；
  2. 请求结束后连接一定归还池子（包括路由抛异常的情况），不泄漏在外；
  3. 应用 shutdown 时池被关闭，再次请求能重建；
  4. 数据库不可达时快速失败（PoolTimeout），而不是把请求挂到平台超时。
"""
from __future__ import annotations

import pytest

import backend.main as main


def test_pool_reuses_connections(client):
    """连续请求不应该每次都新建连接。

    这是连接池存在的全部意义：不设池时 requests_num 会等于连接数。
    """
    for _ in range(20):
        response = client.get("/api/timeline", params={"preset": "all", "page_size": 10})
        assert response.status_code == 200

    stats = main.get_pool().get_stats()
    assert stats.get("requests_num", 0) >= 20
    # 允许比 1 多一点余量：连接被判定为坏掉时池会替换它
    assert stats.get("connections_num", 0) <= 3, (
        f"连接没有被复用：{stats.get('requests_num')} 个请求建立了 "
        f"{stats.get('connections_num')} 条连接"
    )


def _assert_pool_is_actually_used(pool) -> dict:
    """防止空断言。

    如果 get_db 根本没走连接池，池会停在「从未被使用」的状态：此时
    pool_size / pool_available 都是 0，`pool_available == pool_size` 会退化成
    `0 == 0` 恒真 —— 测试看着绿，其实什么都没验证。

    注意 psycopg_pool 的 get_stats() 会**省略值为 0 的计数器**：一个从未服务过
    请求的池只返回 pool_min / pool_max / pool_size / pool_available /
    requests_waiting，连 requests_num 这个 key 都不存在。所以只能 .get()。
    """
    stats = pool.get_stats()
    assert stats.get("requests_num", 0) > 0, (
        "连接池没有被任何请求使用过，后续断言无效（get_db 可能绕过了连接池）"
    )
    return stats


def test_pool_keeps_size_bounded(client):
    """池大小必须受 max_size 约束，不能随请求数增长。"""
    for _ in range(15):
        client.get("/api/stats/providers")
    stats = _assert_pool_is_actually_used(main.get_pool())
    assert stats["pool_max"] == main.DB_POOL_MAX_SIZE
    assert stats["pool_size"] <= main.DB_POOL_MAX_SIZE


def test_connections_returned_to_pool_after_successful_request(client):
    """请求结束后所有连接都应回到池中可用状态。"""
    pool = main.get_pool()
    client.get("/api/stats/providers")
    stats = _assert_pool_is_actually_used(pool)
    assert stats["pool_available"] == stats["pool_size"], (
        f"有连接没归还：available={stats['pool_available']} size={stats['pool_size']}"
    )


def test_connections_returned_to_pool_when_route_raises(client):
    """路由抛异常时连接也必须归还池子，否则池会被慢慢耗尽。

    这条路径正是原来 `conn.close()` 写法最容易出错的地方：异常时连接被直接
    丢弃，而用 `pool.connection()` 会回滚并归还。
    """
    pool = main.get_pool()
    for _ in range(10):
        response = client.post("/api/models/analysis", json={"model_id": "no/such-model"})
        assert response.status_code == 404

    stats = _assert_pool_is_actually_used(pool)
    assert stats["pool_available"] == stats["pool_size"], (
        f"异常路径泄漏了连接：available={stats['pool_available']} size={stats['pool_size']}"
    )


def test_pool_is_closed_on_app_shutdown(seeded_db, monkeypatch):
    """lifespan 退出时必须关掉池，否则本地 --reload 会一路泄漏连接。"""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "DATABASE_URL", seeded_db)
    with TestClient(main.app) as test_client:
        assert test_client.get("/api/stats/providers").status_code == 200
        assert main._pool is not None
    assert main._pool is None, "应用退出后连接池没有被关闭"


def test_pool_can_be_rebuilt_after_shutdown(seeded_db, monkeypatch):
    """关闭后再来请求应当自动重建池，而不是一直报错。"""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "DATABASE_URL", seeded_db)
    with TestClient(main.app) as test_client:
        assert test_client.get("/api/stats/providers").status_code == 200
    assert main._pool is None

    with TestClient(main.app) as test_client:
        response = test_client.get("/api/stats/providers")
        assert response.status_code == 200
        assert response.json(), "重建后的池取不到数据"


def test_pool_fails_fast_when_database_unreachable(monkeypatch):
    """数据库不可达时要抛 PoolTimeout，不能让请求无限挂起。

    Vercel 上函数有时长上限，挂住比快速报错更糟。
    """
    from psycopg_pool import PoolTimeout

    main.close_pool()
    # 127.0.0.1:1 必然不可达，会立刻 connection refused
    monkeypatch.setattr(main, "DATABASE_URL", "postgresql://postgres@127.0.0.1:1/nope")
    monkeypatch.setattr(main, "DB_POOL_TIMEOUT", 1.0)
    monkeypatch.setattr(main, "DB_CONNECT_TIMEOUT", 1)

    try:
        with main.get_pool().connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("select 1")
        pytest.fail("数据库不可达时本应抛 PoolTimeout")
    except PoolTimeout:
        pass
    finally:
        # 把坏池子清掉，避免污染后续测试
        main.close_pool()


def test_pool_config_is_conservative_by_default():
    """默认配置要克制：冷启动不抢连接，池上限要小。

    Supabase 免费层连接数有限，而 serverless 实例会横向放大，
    默认值放大等于更容易打满上游配额。
    """
    assert main.DB_POOL_MIN_SIZE == 0, "min_size 应为 0，避免冷启动与空闲时占用连接配额"
    assert main.DB_POOL_MAX_SIZE <= 8, "max_size 默认不该超过 8"


def test_pool_is_thread_safe_singleton():
    """并发首次调用 get_pool() 只应产生一个池实例。"""
    import threading

    main.close_pool()
    seen: list[int] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        seen.append(id(main.get_pool()))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(seen)) == 1, f"并发下产生了多个池实例：{len(set(seen))}"
