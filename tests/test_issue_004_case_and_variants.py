"""ISSUE-004：OpenRouter 变体 id 过滤 + 大小写归一的回归测试。

不联网、不碰库：
- `is_variant_id` / `select_models` 是纯函数；
- `resolve_case_variant` 用假 cursor；
- 清理脚本的分组与「保留哪一行」规则也在这里锁住。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts import dedupe_models
from src.scraper.fetch_models import resolve_case_variant
from src.scraper.fetch_models_openrouter import is_variant_id, select_models


class _FakeCursor:
    def __init__(self, existing: str | None = None) -> None:
        self.existing = existing
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):  # noqa: ANN001 - 模拟 psycopg cursor
        self.queries.append((sql, params))

    def fetchone(self):
        return (self.existing,) if self.existing else None


# --------------------------------------------------------------------------
# 变体 / 别名 id
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic/claude-opus-4.8:batch",
        "qwen/qwen3-235b-a22b:free",
        "deepseek/deepseek-v4-pro:nitro",
        "google/gemini-3-pro:online",
        "~x-ai/grok-latest",
        "~anthropic/claude-opus-latest",
    ],
)
def test_variant_ids_are_detected(model_id: str) -> None:
    assert is_variant_id(model_id) is True


@pytest.mark.parametrize(
    "model_id",
    ["qwen/qwen3.6-27b", "openai/gpt-4o", "meta-llama/Llama-3.1-70B-Instruct", ""],
)
def test_normal_ids_are_not_variants(model_id: str) -> None:
    assert is_variant_id(model_id) is False


def test_select_models_skips_variants_before_counting() -> None:
    payload = [
        {"id": "qwen/qwen3.6-27b", "name": "Qwen: Qwen3.6 27B"},
        {"id": "qwen/qwen3.6-27b:free", "name": "Qwen: Qwen3.6 27B (free)"},
        {"id": "qwen/qwen3.6-27b:batch", "name": "Qwen: Qwen3.6 27B (batch)"},
        {"id": "~qwen/qwen-latest", "name": "Qwen: Latest"},
    ]

    selected, stats = select_models(payload, {"qwen"}, 0)

    assert [item["id"] for item in selected] == ["qwen/qwen3.6-27b"]
    assert stats["skipped_variants"] == 3
    assert stats["matched_total"] == 1
    assert stats["dropped"] == 0


# --------------------------------------------------------------------------
# 大小写归一
# --------------------------------------------------------------------------
def test_resolve_case_variant_finds_existing_row() -> None:
    cursor = _FakeCursor(existing="Qwen/Qwen3.6-27B")

    assert resolve_case_variant(cursor, "qwen/qwen3.6-27b") == "Qwen/Qwen3.6-27B"
    sql, params = cursor.queries[0]
    assert "lower(model_id) = lower(" in sql
    assert params == ("qwen/qwen3.6-27b",)


def test_resolve_case_variant_returns_none_when_exact_match() -> None:
    cursor = _FakeCursor(existing="qwen/qwen3.6-27b")

    # 同一写法不该被当成「变体」，否则会把本来正确的行改名成它自己
    assert resolve_case_variant(cursor, "qwen/qwen3.6-27b") is None


def test_resolve_case_variant_returns_none_when_missing() -> None:
    assert resolve_case_variant(_FakeCursor(), "qwen/qwen3.6-27b") is None


# --------------------------------------------------------------------------
# 清理脚本：分组 + 保留规则
# --------------------------------------------------------------------------
def _row(model_id: str, *, analyzed=False, desc=False, price=False, tags=0, minutes=0):
    return {
        "model_id": model_id,
        "provider": model_id.split("/")[0],
        "description": desc,
        "price": price,
        "tag_count": tags,
        "analyzed": analyzed,
        "inserted_at": datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc).replace(
            minute=minutes % 60
        ),
    }


def test_group_case_variants_only_returns_duplicate_groups() -> None:
    rows = [
        _row("Qwen/Qwen3.6-27B"),
        _row("qwen/qwen3.6-27b"),
        _row("openai/gpt-4o"),
    ]

    groups = dedupe_models.group_case_variants(rows)

    assert len(groups) == 1
    assert {r["model_id"] for r in groups[0]} == {"Qwen/Qwen3.6-27B", "qwen/qwen3.6-27b"}


def test_plan_keeps_row_with_analysis() -> None:
    rows = [
        _row("Qwen/Qwen3.6-27B", desc=True, tags=5),
        _row("qwen/qwen3.6-27b", analyzed=True),
    ]

    keeper, doomed = dedupe_models.plan(dedupe_models.group_case_variants(rows))[0]

    # 分析记录跟着被保留的那行走，删掉带分析的行等于丢内容
    assert keeper["model_id"] == "qwen/qwen3.6-27b"
    assert [r["model_id"] for r in doomed] == ["Qwen/Qwen3.6-27B"]


def test_plan_prefers_earliest_row_without_analysis() -> None:
    """两边都没有分析时保留**先入库**的那行（通常是 HF，带 org 原始大小写）。

    不按「信息量」优先：先入库那行带 provider=org 原名（meta-llama），另一行带
    OpenRouter 展示名（meta），按信息量选会让 provider 归属无故变化。
    缺的字段（描述 / 价格 / 下载量）由 update 时的合并语句补过来。
    """
    rows = [
        _row("meta-llama/Llama-3.1-70B-Instruct", desc=False, tags=0, minutes=1),
        _row("meta-llama/llama-3.1-70b-instruct", desc=True, price=True, tags=3, minutes=2),
    ]

    keeper, doomed = dedupe_models.plan(dedupe_models.group_case_variants(rows))[0]

    assert keeper["model_id"] == "meta-llama/Llama-3.1-70B-Instruct"
    assert [r["model_id"] for r in doomed] == ["meta-llama/llama-3.1-70b-instruct"]


def test_plan_is_empty_when_no_duplicates() -> None:
    rows = [_row("openai/gpt-4o"), _row("openai/gpt-4o-mini")]

    assert dedupe_models.group_case_variants(rows) == []
    assert dedupe_models.plan([]) == []
