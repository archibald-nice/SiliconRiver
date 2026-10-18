"""排行榜名 → model_id 匹配器测试（纯离线）。

重点守住 ISSUE-001 点名的坑：**尺寸守卫**。``qwen3-vl-235b-a22b-thinking``
绝不能被配到 ``qwen3-vl-30b-a3b-thinking`` 上；宁可 unmatched，也不能把
235B 的分数写到 30B 头上。
"""
from __future__ import annotations

import logging

import pytest

from src.scraper.arena.lmarena import ArenaRow
from src.scraper.arena.matcher import (
    load_aliases,
    match_arena_rows,
    normalize_name,
    scored_forms,
    sizes_compatible,
)


def _row(name: str, category: str = "overall") -> ArenaRow:
    return ArenaRow(
        model_name=name,
        organization=None,
        category=category,
        rank=1,
        score=100.0,
    )


def _ids(matches) -> list[str]:
    return sorted(match.model_id for match in matches)


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Claude-3.5-Sonnet (High)", "claude35sonnet"),
        ("~anthropic/claude-fable-latest", "claudefable"),
        ("Qwen/Qwen3-VL-235B-A22B-Thinking:free", "qwen3vl235ba22bthinking"),
        ("gpt-5.2-preview", "gpt52"),
        ("claude-opus-4-5-20251101", "claudeopus45"),
        ("openai/gpt-5:batch", "gpt5"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_match_ignores_case_and_suffixes():
    matched, unmatched = match_arena_rows(
        [_row("CLAUDE-3-5-SONNET-LATEST")],
        ["anthropic/claude-3.5-sonnet"],
        {},
    )
    assert _ids(matched) == ["anthropic/claude-3.5-sonnet"]
    assert matched[0].method == "exact"
    assert unmatched == []


# ---------------------------------------------------------------------------
# 尺寸守卫（最重要）
# ---------------------------------------------------------------------------


def test_size_guard_rejects_235b_matched_to_30b():
    matched, unmatched = match_arena_rows(
        [_row("Qwen3-VL-235B-A22B-Thinking")],
        ["Qwen/Qwen3-VL-30B-A3B-Thinking"],
        {},
    )
    assert matched == []
    assert len(unmatched) == 1
    assert unmatched[0].model_name == "Qwen3-VL-235B-A22B-Thinking"


def test_size_guard_accepts_same_235b_model():
    matched, unmatched = match_arena_rows(
        [_row("Qwen3-VL-235B-A22B-Thinking")],
        ["Qwen/Qwen3-VL-235B-A22B-Thinking-FP8"],
        {},
    )
    # FP8 是同一权重的量化版，属于允许的模板词差异
    assert _ids(matched) == ["Qwen/Qwen3-VL-235B-A22B-Thinking-FP8"]
    assert unmatched == []


def test_sizes_compatible_requires_both_sides_to_agree():
    assert sizes_compatible("model-70b", "org/model-70b-instruct")
    assert not sizes_compatible("model-70b", "org/model-8b")
    # 缺一侧尺寸也按不一致处理（宁可漏配）
    assert not sizes_compatible("model-70b", "org/model")


def test_size_guard_rejects_substring_trap_even_when_tokens_overlap():
    """名字只差一个数字时，token 子集层也必须被尺寸守卫拦住。"""
    matched, _ = match_arena_rows(
        [_row("Llama-3.1-405B-Instruct")],
        ["meta-llama/Llama-3.1-70B-Instruct"],
        {},
    )
    assert matched == []


# ---------------------------------------------------------------------------
# 别名
# ---------------------------------------------------------------------------


def test_alias_wins_over_fuzzy_matching():
    matched, unmatched = match_arena_rows(
        [_row("Claude Opus 4.6 (High)")],
        ["anthropic/claude-opus-4.6"],
        {"Claude Opus 4.6": "anthropic/claude-opus-4.6"},
    )
    assert _ids(matched) == ["anthropic/claude-opus-4.6"]
    assert matched[0].method == "alias"
    assert unmatched == []


def test_alias_pointing_to_unknown_model_id_is_unmatched_not_guessed(caplog):
    with caplog.at_level(logging.WARNING):
        matched, unmatched = match_arena_rows(
            [_row("Some Model")],
            ["acme/other-model"],
            {"Some Model": "acme/does-not-exist"},
        )
    assert matched == []
    assert len(unmatched) == 1
    assert "不在库里" in caplog.text


def test_load_aliases_merges_shared_and_source_sections(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text(
        "shared:\n  'A': 'acme/a'\n"
        "lmarena:\n  'B': 'acme/b'\n"
        "swebench:\n  'B': 'acme/b-swe'\n",
        encoding="utf-8",
    )
    assert load_aliases(path, source="lmarena") == {"A": "acme/a", "B": "acme/b"}
    assert load_aliases(path, source="swebench")["B"] == "acme/b-swe"


def test_load_aliases_missing_file_returns_empty(tmp_path):
    assert load_aliases(tmp_path / "nope.yaml") == {}


# ---------------------------------------------------------------------------
# unmatched 如实返回 / 多候选
# ---------------------------------------------------------------------------


def test_unmatched_is_reported_honestly():
    matched, unmatched = match_arena_rows(
        [_row("Totally Unknown Model")],
        ["acme/model-70b"],
        {},
    )
    assert matched == []
    assert len(unmatched) == 1
    assert unmatched[0].model_name == "Totally Unknown Model"


def test_variant_suffix_candidates_share_the_same_score():
    """``:batch`` 只是 OpenRouter 的服务变体，和基础条目是同一个模型。"""
    matched, _ = match_arena_rows(
        [_row("GPT-5.2")],
        ["openai/gpt-5.2", "openai/gpt-5.2:batch"],
        {},
    )
    assert _ids(matched) == ["openai/gpt-5.2", "openai/gpt-5.2:batch"]


def test_date_variant_does_not_leak_score_onto_base_model():
    matched, _ = match_arena_rows(
        [_row("claude-opus-4-5-20251101")],
        ["anthropic/claude-opus-4-5", "anthropic/claude-opus-4-5-20251101"],
        {},
    )
    # 精确命中日期快照那条，不把分数同时写给基础模型
    assert _ids(matched) == ["anthropic/claude-opus-4-5-20251101"]


def test_rows_without_model_name_are_unmatched():
    broken = ArenaRow(model_name="", organization=None, category="overall", rank=1, score=1.0)
    matched, unmatched = match_arena_rows([broken], ["acme/model-70b"], {})
    assert matched == []
    assert len(unmatched) == 1


def test_stacked_effort_and_context_suffixes_still_match():
    """``-20251101-high-32k`` 是“快照+推理档+上下文”三合一，仍属同一个快照。"""
    matched, _ = match_arena_rows(
        [_row("claude-opus-4-5-20251101-high-32k")],
        ["anthropic/claude-opus-4-5-20251101"],
        {},
    )
    assert _ids(matched) == ["anthropic/claude-opus-4-5-20251101"]


def test_row_org_prefix_and_quantization_suffix_are_tolerated():
    """行名把 org（nvidia）和量化格式（nvfp4）写进名字，权重仍是同一个。"""
    matched, _ = match_arena_rows(
        [_row("nvidia-nemotron-3-ultra-550b-a55b-nvfp4")],
        ["nvidia/nemotron-3-ultra-550b-a55b"],
        {},
    )
    assert _ids(matched) == ["nvidia/nemotron-3-ultra-550b-a55b"]


def test_row_org_token_does_not_defeat_size_guard():
    """补 org token 不能顺带放开尺寸守卫：550b 仍配不到 30b。"""
    matched, unmatched = match_arena_rows(
        [_row("nvidia-nemotron-3-ultra-550b-a55b-nvfp4")],
        ["nvidia/nemotron-3-nano-30b-a3b"],
        {},
    )
    assert matched == []
    assert len(unmatched) == 1


def test_fuzzy_hits_that_are_only_variants_share_the_score():
    """模糊层遇到 ``:free`` 变体时，和 exact 层一样两边都给，不判歧义。"""
    matched, unmatched = match_arena_rows(
        [_row("nvidia-nemotron-3-ultra-550b-a55b-nvfp4")],
        ["nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-ultra-550b-a55b:free"],
        {},
    )
    assert _ids(matched) == [
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
    ]
    assert unmatched == []


def test_marker_behind_effort_is_still_stripped():
    """``-preview`` 压在档位后面时，循环剥完要能回到基础名。"""
    forms = dict(scored_forms("deepseek-v4-pro-high-preview"))
    assert forms.get("deepseekv4pro") == 1


def test_stacked_markers_with_separators_collapse():
    assert normalize_name("gpt-5-preview-latest") == "gpt5"
