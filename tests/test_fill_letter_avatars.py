"""`scripts/fill_letter_avatars.py` 的纯函数测试（不碰数据库、不联网）。"""

from __future__ import annotations

import re

from scripts.fill_letter_avatars import (
    PALETTE,
    background_for,
    build_letter_avatar_svg,
    letter_for,
)


def test_letter_prefers_display_name_initial() -> None:
    assert letter_for("Nex AGI", "nex agi") == "N"
    assert letter_for("thedrummer", "thedrummer") == "T"


def test_letter_trims_whitespace_and_handles_missing_name() -> None:
    assert letter_for("  mochi  ", "mochi") == "M"
    assert letter_for(None, "z-ai") == "Z"
    assert letter_for("", "qwen") == "Q"


def test_letter_uppercases_and_keeps_cjk() -> None:
    assert letter_for("deepseek", "deepseek") == "D"
    assert letter_for("月之暗面", "moonshot") == "月"


def test_background_is_stable_per_provider() -> None:
    assert background_for("nex agi") == background_for("nex agi")
    assert background_for("nex agi") in {color for color, _ in PALETTE}


def test_svg_contains_letter_and_is_well_formed() -> None:
    svg = build_letter_avatar_svg("Nex AGI", "nex agi")
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert ">N<" in svg
    assert "image/svg+xml" not in svg  # 主体是图形不是元数据
    assert len(svg) < 1000


def test_svg_escapes_nothing_dangerous_for_single_char() -> None:
    # 单字符只可能是字母/汉字，给个极端输入也必须是单字符，不会注入结构
    svg = build_letter_avatar_svg("<script>", "<script>")
    letter_match = re.search(r">([^<]*)</text>", svg)
    assert letter_match is not None
    assert len(letter_match.group(1)) == 1
