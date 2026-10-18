"""SWE-bench 解析层离线测试（禁止真实网络）。

覆盖：内嵌 JSON 抠取（HTML 前后文干扰）、按模型去重取最高分、
并列名次计算、Verified/Lite 分组过滤、多模型系统跳过。
"""
from __future__ import annotations

import json

import pytest

from src.scraper.arena import swebench


def _entry(
    *,
    name: str,
    slug: str,
    resolved: float,
    org: str = "acme",
    date: str = "2026-01-01",
    extra_models: tuple[str, ...] = (),
) -> dict:
    return {
        "name": name,
        "model_display": name,
        "model_org": org,
        "agent": "mini-swe-agent",
        "date": date,
        "folder": name,
        "tags": ["Model: " + slug, *("Model: " + item for item in extra_models)],
        "resolved": resolved,
    }


def _payload() -> list[dict]:
    return [
        {"name": "Verified", "results": []},
        {"name": "Lite", "results": []},
        {"name": "Multimodal", "results": []},
    ]


def _html(blocks: list[dict], before: str = "<html><body>", after: str = "</body></html>") -> str:
    return (
        before
        + '<script type="application/json" id="leaderboard-data">'
        + json.dumps(blocks)
        + "</script>"
        + after
    )


# ---------------------------------------------------------------------------
# JSON 抠取
# ---------------------------------------------------------------------------


def test_extract_leaderboard_json_ignores_surrounding_html():
    blocks = _payload()
    data = swebench.extract_leaderboard_json(_html(blocks))
    assert [block["name"] for block in data] == ["Verified", "Lite", "Multimodal"]


def test_extract_leaderboard_json_tolerates_newlines_in_script():
    html = (
        "<html><script id='leaderboard-data' type='application/json'>\n"
        '[{"name": "Verified", "results": []}]\n'
        "</script></html>"
    )
    assert swebench.extract_leaderboard_json(html) == [{"name": "Verified", "results": []}]


def test_extract_leaderboard_json_raises_when_script_missing():
    with pytest.raises(swebench.SweBenchParseError):
        swebench.extract_leaderboard_json("<html><body>no data</body></html>")


def test_extract_leaderboard_json_raises_on_invalid_json():
    html = '<script id="leaderboard-data">{not json}</script>'
    with pytest.raises(swebench.SweBenchParseError):
        swebench.extract_leaderboard_json(html)


# ---------------------------------------------------------------------------
# 解析：去重 + rank
# ---------------------------------------------------------------------------


def test_parse_dedupes_by_normalized_model_and_keeps_best_resolved():
    blocks = _payload()
    blocks[0]["results"] = [
        _entry(name="claude-opus-4-5", slug="claude-opus-4-5", resolved=70.0),
        # 同一个模型的日期快照版本，分数更高 → 去重后应保留 74.5
        _entry(
            name="claude-opus-4-5-20251101",
            slug="claude-opus-4-5-20251101",
            resolved=74.5,
        ),
    ]
    rows = swebench.parse_leaderboard_data(blocks)

    verified = [row for row in rows if row.category == "verified"]
    assert len(verified) == 1
    assert verified[0].score == pytest.approx(74.5)
    assert verified[0].model_name == "claude-opus-4-5-20251101"


def test_parse_rank_ties_share_rank_and_next_position_skips():
    blocks = _payload()
    blocks[0]["results"] = [
        _entry(name="a", slug="model-a", resolved=80.0),
        _entry(name="b", slug="model-b", resolved=70.0),
        _entry(name="c", slug="model-c", resolved=70.0),
        _entry(name="d", slug="model-d", resolved=60.0),
    ]
    rows = {row.model_name: row for row in swebench.parse_leaderboard_data(blocks)}
    assert rows["model-a"].rank == 1
    assert rows["model-b"].rank == 2
    assert rows["model-c"].rank == 2
    assert rows["model-d"].rank == 4


def test_parse_only_emits_requested_groups():
    blocks = _payload()
    blocks[0]["results"] = [_entry(name="v", slug="v-model", resolved=10.0)]
    blocks[1]["results"] = [_entry(name="l", slug="l-model", resolved=20.0)]
    blocks[2]["results"] = [_entry(name="m", slug="m-model", resolved=30.0)]

    rows = swebench.parse_leaderboard_data(blocks)
    assert {row.category for row in rows} == {"verified", "lite"}
    assert {row.model_name for row in rows} == {"v-model", "l-model"}


def test_parse_skips_systems_with_multiple_models():
    blocks = _payload()
    blocks[0]["results"] = [
        _entry(name="multi", slug="model-a", resolved=90.0, extra_models=("model-b", "model-c")),
        _entry(name="single", slug="model-d", resolved=50.0),
    ]
    rows = swebench.parse_leaderboard_data(blocks)
    assert [row.model_name for row in rows] == ["model-d"]


def test_parse_skips_entries_without_model_tag():
    blocks = _payload()
    blocks[0]["results"] = [
        {"name": "Undisclosed", "tags": [], "resolved": 99.0},
        {"name": "Missing", "resolved": 98.0},
        _entry(name="ok", slug="ok-model", resolved=40.0),
    ]
    rows = swebench.parse_leaderboard_data(blocks)
    assert [row.model_name for row in rows] == ["ok-model"]


def test_parse_missing_group_raises():
    with pytest.raises(swebench.SweBenchParseError):
        swebench.parse_leaderboard_data([{"name": "Verified", "results": []}])


def test_fetch_swebench_rows_limit_truncates_after_ranking(monkeypatch):
    blocks = _payload()
    blocks[0]["results"] = [
        _entry(name="a", slug="model-a", resolved=80.0),
        _entry(name="b", slug="model-b", resolved=70.0),
    ]
    blocks[1]["results"] = []
    monkeypatch.setattr(
        swebench, "fetch_html", lambda **kwargs: _html(blocks)
    )
    rows = swebench.fetch_swebench_rows(limit=1)
    assert len(rows) == 1
    assert rows[0].model_name == "model-a"
    assert rows[0].rank == 1
