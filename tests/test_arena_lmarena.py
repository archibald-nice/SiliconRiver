"""LMArena 抓取层离线测试（禁止真实网络）。

覆盖四件事：

1. 翻页 URL 拼接（offset/length，length 必须 ≤ 100）；
2. ``/rows`` 响应解析（字段映射 + 脏行跳过）；
3. parquet 直读分支（首选路径）与它失败后的回落；
4. 失败重试与重试耗尽后的失败语义（**不返回部分数据、不回落假数据**）。
"""
from __future__ import annotations

import pytest
import requests

from src.scraper.arena import lmarena


class FakeResponse:
    def __init__(self, payload=None, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def _disable_parquet(monkeypatch):
    """默认关掉 parquet 分支：下面的用例测的是 ``/rows`` 翻页逻辑。

    parquet 分支有独立用例覆盖。不关掉的话它会读项目内 HF 缓存
    （``data/cache/hf``），把真实的 11,033 行喂进断言。
    """

    def _disabled():
        raise lmarena.ArenaFetchError("parquet disabled in tests")

    monkeypatch.setattr(lmarena, "fetch_latest_parquet_files", _disabled)


def _row_payload(total: int, model_name: str, category: str = "overall") -> dict:
    return {
        "rows": [
            {
                "row": {
                    "model_name": model_name,
                    "organization": "Acme",
                    "category": category,
                    "rank": 7,
                    "rating": 1200.5,
                    "rating_lower": 1190,
                    "rating_upper": 1210,
                    "vote_count": 1234,
                    "leaderboard_publish_date": "2026-10-01",
                }
            }
        ],
        "num_rows_total": total,
    }


# ---------------------------------------------------------------------------
# URL 拼接
# ---------------------------------------------------------------------------


def test_build_rows_url_encodes_dataset_and_pagination():
    url = lmarena.build_rows_url(200, 100)
    assert url.startswith("https://datasets-server.huggingface.co/rows?")
    assert "dataset=lmarena-ai%2Fleaderboard-dataset" in url
    assert "config=text" in url
    assert "split=latest" in url
    assert "offset=200" in url
    assert "length=100" in url


@pytest.mark.parametrize("length", [0, 101, 500])
def test_build_rows_url_rejects_illegal_length(length):
    # 实测 length>100 返回 422，所以本地就把上限卡住，别把 422 留到线上。
    with pytest.raises(ValueError):
        lmarena.build_rows_url(0, length)


def test_build_rows_url_rejects_negative_offset():
    with pytest.raises(ValueError):
        lmarena.build_rows_url(-1, 10)


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------


def test_parse_rows_payload_maps_fields():
    rows = lmarena.parse_rows_payload(_row_payload(11033, "Claude Opus 4.6"))
    assert len(rows) == 1
    row = rows[0]
    assert row.model_name == "Claude Opus 4.6"
    assert row.organization == "Acme"
    assert row.category == "overall"
    assert row.rank == 7
    assert row.score == pytest.approx(1200.5)
    assert row.vote_count == pytest.approx(1234)
    assert row.publish_date == "2026-10-01"


def test_parse_rows_payload_skips_rows_without_name_or_category():
    payload = {
        "rows": [
            {"row": {"model_name": "ok", "category": "overall"}},
            {"row": {"model_name": "", "category": "overall"}},
            {"row": {"model_name": "no-category"}},
            {"row": None},
            "not-a-dict",
        ]
    }
    rows = lmarena.parse_rows_payload(payload)
    assert [row.model_name for row in rows] == ["ok"]


def test_parse_rows_payload_rejects_missing_rows_array():
    with pytest.raises(lmarena.ArenaFetchError):
        lmarena.parse_rows_payload({})


# ---------------------------------------------------------------------------
# 并发翻页
# ---------------------------------------------------------------------------


def test_fetch_latest_rows_pages_by_100_and_stops_at_total(monkeypatch):
    requested: list[str] = []

    def fake_get(url, timeout=30):
        requested.append(url)
        offset = int(url.rsplit("offset=", 1)[1].split("&")[0])
        length = int(url.rsplit("length=", 1)[1])
        return FakeResponse(_row_payload(250, f"model-{offset}-{length}"))

    monkeypatch.setattr(lmarena, "_http_get", fake_get)
    rows = lmarena.fetch_latest_rows(workers=4)

    assert len(rows) == 3
    # 250 行 → 3 页：0/100/200（第三页 length=50）
    assert "offset=0&" in requested[0] and "length=100" in requested[0]
    assert any("offset=100&" in url and "length=100" in url for url in requested)
    assert any("offset=200&" in url and "length=50" in url for url in requested)


def test_fetch_latest_rows_applies_limit_without_overfetching(monkeypatch):
    requested: list[str] = []

    def fake_get(url, timeout=30):
        requested.append(url)
        offset = int(url.rsplit("offset=", 1)[1].split("&")[0])
        length = int(url.rsplit("length=", 1)[1])
        return FakeResponse(_row_payload(250, f"model-{offset}-{length}"))

    monkeypatch.setattr(lmarena, "_http_get", fake_get)
    rows = lmarena.fetch_latest_rows(limit=150, workers=2)

    assert len(rows) == 2  # 每页只回 1 行（fake 简化），页数才是断言重点
    assert not any("offset=200" in url for url in requested)
    assert any("length=50" in url for url in requested)


def test_fetch_latest_rows_raises_when_num_rows_total_missing(monkeypatch):
    monkeypatch.setattr(lmarena, "_http_get", lambda url, timeout=30: FakeResponse({"rows": []}))
    with pytest.raises(lmarena.ArenaFetchError):
        lmarena.fetch_latest_rows()


# ---------------------------------------------------------------------------
# 重试
# ---------------------------------------------------------------------------


def test_fetch_page_retries_transient_error_then_succeeds(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky_get(url, timeout=30):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("boom")
        return FakeResponse(_row_payload(1, "claude"))

    monkeypatch.setattr(lmarena, "_http_get", flaky_get)
    monkeypatch.setattr(lmarena.time, "sleep", lambda seconds: sleeps.append(seconds))

    payload = lmarena.fetch_page(0, 100, max_retries=3)
    assert calls["n"] == 3
    assert sleeps == [1.5, 3.0]
    assert payload["num_rows_total"] == 1


def test_fetch_page_gives_up_after_max_retries(monkeypatch):
    calls = {"n": 0}

    def always_fail(url, timeout=30):
        calls["n"] += 1
        raise requests.Timeout("timeout")

    monkeypatch.setattr(lmarena, "_http_get", always_fail)
    monkeypatch.setattr(lmarena.time, "sleep", lambda seconds: None)

    with pytest.raises(lmarena.ArenaFetchError):
        lmarena.fetch_page(0, 100, max_retries=2)
    assert calls["n"] == 2


def test_fetch_page_retries_http_500(monkeypatch):
    calls = {"n": 0}

    def flaky_get(url, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse({"rows": []}, status_code=500)
        return FakeResponse(_row_payload(1, "claude"))

    monkeypatch.setattr(lmarena, "_http_get", flaky_get)
    monkeypatch.setattr(lmarena.time, "sleep", lambda seconds: None)

    payload = lmarena.fetch_page(0, 100, max_retries=2)
    assert calls["n"] == 2
    assert payload["num_rows_total"] == 1


def test_any_page_failure_fails_whole_fetch(monkeypatch):
    """部分成功也不行：少一页会让 category 内排名看起来“少了一些模型”。"""

    def fake_get(url, timeout=30):
        offset = int(url.rsplit("offset=", 1)[1].split("&")[0])
        if offset > 0:
            raise requests.ConnectionError("page 2 down")
        return FakeResponse(_row_payload(250, "claude"))

    monkeypatch.setattr(lmarena, "_http_get", fake_get)
    monkeypatch.setattr(lmarena.time, "sleep", lambda seconds: None)

    with pytest.raises(lmarena.ArenaFetchError):
        lmarena.fetch_latest_rows(workers=2, max_retries=1)


def test_fetch_page_backs_off_longer_on_http_429(monkeypatch):
    """429 是分钟级限流配额，1.5s 线性退避等不到恢复，必须放大到 5s 起步。"""
    calls = {"n": 0}
    sleeps: list[float] = []

    def rate_limited(url, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse({"rows": []}, status_code=429)
        return FakeResponse(_row_payload(1, "claude"))

    monkeypatch.setattr(lmarena, "_http_get", rate_limited)
    monkeypatch.setattr(lmarena.time, "sleep", lambda seconds: sleeps.append(seconds))

    lmarena.fetch_page(0, 100, max_retries=2)
    assert sleeps == [5.0]


# ---------------------------------------------------------------------------
# parquet 分支
# ---------------------------------------------------------------------------


def _parquet_record(model_name: str, category: str = "overall", **overrides) -> dict:
    record = {
        "model_name": model_name,
        "organization": "Acme",
        "category": category,
        "rank": 3,
        "rating": 1200.5,
        "vote_count": 4321,
        "leaderboard_publish_date": "2026-10-15",
    }
    record.update(overrides)
    return record


def test_parse_parquet_records_maps_columns_and_skips_bad_rows():
    rows = lmarena.parse_parquet_records(
        [
            _parquet_record("claude-4"),
            _parquet_record("", category="overall"),  # 缺 model_name
            {"organization": "Acme"},  # 缺 category/model_name
            "not-a-dict",
        ]
    )

    assert len(rows) == 1
    assert rows[0].model_name == "claude-4"
    assert rows[0].score == 1200.5
    assert rows[0].rank == 3
    assert rows[0].vote_count == 4321
    assert rows[0].publish_date == "2026-10-15"


def test_fetch_latest_rows_prefers_parquet_and_never_pages(monkeypatch):
    """parquet 是首选路径：不许再打 datasets-server 的 /rows（实测会 429）。"""
    monkeypatch.setattr(
        lmarena,
        "fetch_latest_parquet_files",
        lambda: [_parquet_record("claude-4"), _parquet_record("gpt-4o")],
    )

    def _forbidden(url, timeout=30):  # pragma: no cover - 走到这里就该失败
        raise AssertionError("parquet 成功时不应请求 /rows")

    monkeypatch.setattr(lmarena, "_http_get", _forbidden)

    rows = lmarena.fetch_latest_rows()

    assert [row.model_name for row in rows] == ["claude-4", "gpt-4o"]


def test_fetch_latest_rows_respects_limit_on_parquet_path(monkeypatch):
    monkeypatch.setattr(
        lmarena,
        "fetch_latest_parquet_files",
        lambda: [_parquet_record(f"m{i}") for i in range(5)],
    )

    rows = lmarena.fetch_latest_rows(limit=2)

    assert [row.model_name for row in rows] == ["m0", "m1"]


def test_fetch_latest_rows_falls_back_to_rows_when_parquet_fails(monkeypatch):
    monkeypatch.setattr(
        lmarena,
        "fetch_latest_parquet_files",
        lambda: (_ for _ in ()).throw(lmarena.ArenaFetchError("boom")),
    )
    monkeypatch.setattr(
        lmarena, "_http_get", lambda url, timeout=30: FakeResponse(_row_payload(1, "claude"))
    )

    rows = lmarena.fetch_latest_rows()

    assert [row.model_name for row in rows] == ["claude"]
