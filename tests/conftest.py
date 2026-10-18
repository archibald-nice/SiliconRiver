"""pytest 共享配置。

两个原则：
1. 需要数据库的测试自己声明依赖（`db_client`），没配 TEST_DATABASE_URL 就跳过，
   不要让整个 tests/ 目录一起被 skip 掉。
2. 测试库会被**清空重建**，所以只允许指向名字里带 test 的库，防止误删开发库。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

# 复用项目自己的 .env（里面已经配好本地开发库）
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="需要 TEST_DATABASE_URL（见 .env，本地用 scripts/dev_db.sh start 起库）",
)


# ---------------------------------------------------------------------------
# 网络守门：默认禁止用例访问真实网络（ISSUE-033）
# ---------------------------------------------------------------------------
# 这个仓库踩过两次「测试悄悄打真实网络」的坑：排行榜用例三个客户端里只 mock 了
# 一个，另外两个真发请求，整个文件 206 秒；分析并发用例没替换标签生成器，200 个
# 模型真打了 200 次 LLM，160 秒。真网络还会让 CI 随机红、把测试结果和上游状态
# 绑死。与其靠 review 记着 mock，不如默认把外网掐掉：需要真网络时给用例显式加
# @pytest.mark.allow_network（目前一个都没有）。
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", ""}


def _is_allowed_host(host: object) -> bool:
    if not isinstance(host, str):
        return False  # AF_UNIX 路径或其它形态，交给调用方
    if host in _ALLOWED_HOSTS:
        return True
    return host.startswith("127.") or host.startswith("/")


@pytest.fixture(autouse=True)
def _deny_external_network(monkeypatch, request):
    if request.node.get_closest_marker("allow_network"):
        return

    import socket

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(address):
        host = address[0] if isinstance(address, tuple) and address else None
        if host is not None and not _is_allowed_host(host):
            raise RuntimeError(
                f"测试禁止访问真实网络：{address!r}。"
                "请 mock 掉该调用；确实需要联网时给用例加 @pytest.mark.allow_network"
            )

    def guarded_connect(sock, address):
        _check(address)
        return real_connect(sock, address)

    def guarded_connect_ex(sock, address):
        _check(address)
        return real_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


def _assert_safe_test_db(url: str) -> None:
    """防止把测试指向开发库或生产库后被清表。"""
    name = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in name.lower():
        raise RuntimeError(
            f"拒绝对疑似非测试库执行清表：{url!r}。"
            "数据库名里必须含 'test' 才能跑这些测试。"
        )


@pytest.fixture(scope="session")
def db_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("需要 TEST_DATABASE_URL")
    _assert_safe_test_db(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


def seed_sample_data(db_url: str) -> None:
    """清空测试库并写入那套确定性样本数据（acme/globex 三个模型）。

    抽成独立函数是因为它有两个调用方：`seeded_db`（session 级，开工时建一次）
    与 `ensure_seeded`（用例级，被别的测试清库之后补回来）。样本数据原先只塞
    一次，于是执行顺序一换就炸：`tests/test_fetch_models.py` 会 TRUNCATE 整个
    库，排在它后面的路由测试就全查不到行（表现为 `total == 0`、`KeyError:
    'provider'`），单独跑那个文件却又是绿的。
    """
    import psycopg

    from scripts.init_db import create_schema

    # 先探一下连通性，连不上就**跳过**而不是让几十个用例一起 ERROR。
    # 这个场景会经常发生：.env 的 DATABASE_URL 指向 Supabase（生产），而
    # TEST_DATABASE_URL 指向本机库；本机库没起时，之前每个用例都会抛
    # OperationalError，看起来像"代码改坏了"，其实只是没跑 dev_db.sh start。
    try:
        with psycopg.connect(db_url, connect_timeout=3):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"测试库不可达：{exc}\n"
            "  → 本地跑测试前先执行：bash scripts/dev_db.sh start"
        )

    create_schema(db_url)

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        # 清表：顺序照顾外键（model_tags / model_arena_info -> models）
        cur.execute(
            "TRUNCATE model_tags, model_arena_info, model_analysis, sync_log, models, providers "
            "RESTART IDENTITY CASCADE"
        )

        cur.execute(
            """
            INSERT INTO providers (provider_id, display_name, avatar_url)
            VALUES ('acme', 'Acme', NULL), ('globex', 'Globex', NULL)
            """
        )
        cur.execute(
            """
            INSERT INTO models
                (model_id, provider, model_name, description, tags, created_at,
                 downloads, likes, model_card_url, inserted_at, is_open_source,
                 price, huggingface_rank)
            VALUES
                ('acme/alpha-1', 'acme', 'Alpha 1', 'first model', '["llm"]',
                 '2024-01-15 00:00:00', 100, 10, 'https://example.com/a1',
                 '2024-01-15 00:00:00', TRUE, NULL, 1),
                ('acme/beta-2', 'acme', 'Beta 2', 'second model', '["llm","vision"]',
                 '2024-06-20 00:00:00', 200, 20, 'https://example.com/b2',
                 '2024-06-20 00:00:00', FALSE, NULL, 2),
                ('globex/gamma-3', 'globex', 'Gamma 3', 'third model', '["vision"]',
                 '2025-03-05 00:00:00', 300, 30, 'https://example.com/g3',
                 '2025-03-05 00:00:00', TRUE, NULL, 3)
            """
        )
        cur.execute(
            """
            INSERT INTO model_tags (model_id, tag) VALUES
                ('acme/alpha-1', 'llm'), ('acme/beta-2', 'llm'),
                ('acme/beta-2', 'vision'), ('globex/gamma-3', 'vision')
            """
        )
        cur.execute(
            """
            INSERT INTO model_analysis
                (model_id, provider, model_name, analysis_summary, key_features,
                 use_cases, llm_model_used, is_milestone, milestone_features)
            VALUES
                ('acme/alpha-1', 'acme', 'Alpha 1', 'a summary',
                 ARRAY['fast'], ARRAY['chat'], 'deepseek-chat', TRUE, 'first')
            """
        )
        cur.execute(
            """
            INSERT INTO model_arena_info (model_id, source, rank, score, category)
            VALUES
                ('acme/alpha-1', 'swe-bench', 3, 71.2, 'overall'),
                ('acme/alpha-1', 'lmsys', 5, 1200.5, 'overall')
            """
        )

@pytest.fixture(scope="session")
def seeded_db(db_url: str) -> str:
    """开工时建表并塞入样本数据（session 级，只跑一次）。"""
    seed_sample_data(db_url)
    return db_url


@pytest.fixture()
def ensure_seeded(seeded_db: str) -> str:
    """样本数据被别的用例清掉后补回来。

    `tests/test_fetch_models.py` 会 TRUNCATE 整库来验证写库逻辑，而 pytest 按
    文件名顺序收集，它排在多数 `test_issue_*` 之前。只塞一次的 session 级样本
    因此会在中途消失，后面的路由测试读到空库。这里在每条用例前做一次极廉价的
    探测（`SELECT 1 FROM models LIMIT 1`），发现没了就重新播种——代价是每条
    用例多一次索引探测，换来的是「单跑绿、全跑红」这类顺序依赖消失。
    """
    import psycopg

    # 探测必须盯住样本里的**具体行**，不能只问「库里有没有模型」：
    # test_fetch_models.py 清库后会写回自己的 meta-llama/* 行，只探存在性会
    # 误判为健康，而 acme/alpha-1 其实已经不在了。
    with psycopg.connect(seeded_db) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM models WHERE model_id = 'acme/alpha-1'")
        healthy = cur.fetchone() is not None
    if not healthy:
        seed_sample_data(seeded_db)
    return seeded_db


@pytest.fixture()
def client(ensure_seeded: str, monkeypatch: pytest.MonkeyPatch):
    """指向测试库的 TestClient。"""
    from fastapi.testclient import TestClient

    import backend.main as main

    monkeypatch.setattr(main, "DATABASE_URL", ensure_seeded)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client
