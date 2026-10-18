"""ISSUE-019（头像接口 SSRF）与 ISSUE-023（ILIKE 通配符 / 搜索串长度）的回归测试。

019 里可测的只有两件事：白名单判定是纯函数；路由层对不可信 URL 必须 403 而不是发请求。
023 则需要真库——`%` 被当成通配符时 `total` 会等于全表，转义后必须为 0。

不需要数据库的用例只 import 纯函数；需要数据的用例复用 `client` / `db_url` fixture，
没配 `TEST_DATABASE_URL` 时由 conftest 自动跳过。
"""
from __future__ import annotations

import psycopg
import pytest

import backend.main as main


# ---------- ISSUE-019：白名单判定（无数据库） ----------

@pytest.mark.parametrize(
    "url",
    [
        "https://cdn-avatars.huggingface.co/v1/production/avatar.png",
        "https://huggingface.co/avatars/x.png",
        "http://avatars.githubusercontent.com/u/1",
        "HTTPS://CDN-AVATARS.HUGGINGFACE.CO/x.png",  # 大小写不敏感
        "https://cdn-avatars.huggingface.co:443/x.png",
    ],
)
def test_avatar_target_allowed_accepts_whitelisted_hosts(url: str) -> None:
    assert main._avatar_target_allowed(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x.png",                    # 回环
        "http://10.0.0.5/x.png",                     # 内网
        "http://169.254.169.254/latest/meta-data",   # 云元数据
        "http://[::1]/x.png",                        # IPv6 回环
        "file:///etc/passwd",                        # 非 http 协议
        "gopher://huggingface.co/x",                 # 非 http 协议
        "https://cdn-avatars.huggingface.co.evil.com/x.png",  # 后缀伪装
        "https://huggingface.co@127.0.0.1/x.png",    # userinfo 伪装
        "https://cdn-avatars.huggingface.co:8443/x.png",      # 非常规端口
        "https://not-in-list.example.com/x.png",     # 白名单外
        "https:///no-host",                          # 无主机
    ],
)
def test_avatar_target_allowed_rejects_untrusted_targets(url: str) -> None:
    assert main._avatar_target_allowed(url) is False


# ---------- ISSUE-023：转义函数（无数据库） ----------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("alpha", "alpha"),
        ("%", r"\%"),
        ("_", r"\_"),
        (r"a\b", r"a\\b"),
        (r"\%_", r"\\\%\_"),  # 反斜杠必须先转，否则会把后加的转义符再转一遍
    ],
)
def test_escape_like(raw: str, expected: str) -> None:
    assert main._escape_like(raw) == expected


# ---------- 库内样本（自给自足，不依赖别的用例留下的数据） ----------

def _ensure_seed_rows(db_url: str) -> None:
    """确保 `acme` 厂商与 `acme/alpha-1` 模型存在。

    全量跑时别的用例会写/清测试库（`test_fetch_models`、集成用例都直连同一个库），
    session 级 `seeded_db` 塞的数据不保证到本文件还在——曾经就因为 provider 行没了，
    头像用例拿到 404 而不是 403。这里用 upsert 自己兜住。
    """
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO providers (provider_id, display_name)
            VALUES ('acme', 'Acme')
            ON CONFLICT (provider_id) DO NOTHING
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
                 '2024-01-15 00:00:00', TRUE, NULL, 1)
            ON CONFLICT (model_id) DO NOTHING
            """
        )


# ---------- ISSUE-019：路由层拒绝（需要数据库） ----------

def _set_avatar_columns(
    db_url: str, provider_id: str, url: str, blob: bytes | None = None
) -> None:
    """直接改 providers 的头像列（url + 缓存字节）。

    必须连 blob 一起清：只要 `avatar_blob` 有值，路由会**直接回缓存、根本不过白名单**
    （见 `provider_avatar`），别的用例先缓存成功过一次，这里就会变成 200。
    """
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE providers
               SET avatar_url = %s, avatar_blob = %s, avatar_mime = %s
             WHERE provider_id = %s
            """,
            (url, blob, "image/png" if blob is not None else None, provider_id),
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/avatar.png",
        "https://cdn-avatars.huggingface.co.evil.com/avatar.png",
    ],
)
def test_avatar_route_rejects_untrusted_source(client, db_url: str, url: str) -> None:
    """不可信 URL 必须 403，且不能真的发出上游请求（这里没有网络也会是 403）。"""
    _ensure_seed_rows(db_url)
    _set_avatar_columns(db_url, "acme", url)
    try:
        response = client.get("/api/providers/acme/avatar")
        assert response.status_code == 403, response.text
    finally:
        _set_avatar_columns(db_url, "acme", None)


# ---------- ISSUE-023：路由层行为（需要数据库） ----------

@pytest.mark.parametrize("wildcard", ["%", "_", "%%"])
def test_timeline_search_treats_wildcards_literally(client, db_url: str, wildcard: str) -> None:
    # `preset=all` 是必须的：默认 preset=30d 会把样本数据（2024/2025 年）全过滤掉，
    # 那样断言 total==0 是恒真的，等于什么都没测。
    # 样本库里没有模型名含 % 或 _，因此转义后应当查不到东西；
    # 未转义时 `%` 会匹配全表（total > 0），这正是本用例要锁住的行为。
    _ensure_seed_rows(db_url)
    response = client.get("/api/timeline", params={"model_name": wildcard, "preset": "all"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_timeline_search_still_matches_plain_substring(client, db_url: str) -> None:
    _ensure_seed_rows(db_url)
    response = client.get("/api/timeline", params={"model_name": "alpha", "preset": "all"})
    assert response.status_code == 200
    ids = [item["model_id"] for item in response.json()["items"]]
    assert "acme/alpha-1" in ids


@pytest.mark.parametrize(
    "path",
    ["/api/timeline", "/api/models", "/api/models/analyzed"],
)
def test_overlong_search_string_is_rejected(client, path: str) -> None:
    """超长搜索串直接 422 拒绝，而不是截断后静默返回别的东西。"""
    param = "model_name" if path == "/api/timeline" else "search"
    response = client.get(path, params={param: "x" * 65})
    assert response.status_code == 422, response.text

    ok = client.get(path, params={param: "x" * 64})
    assert ok.status_code == 200, ok.text
